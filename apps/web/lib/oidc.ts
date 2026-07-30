const config = {
  authority: process.env.NEXT_PUBLIC_OIDC_AUTHORITY ?? "",
  clientId: process.env.NEXT_PUBLIC_OIDC_CLIENT_ID ?? "",
  redirectUri:
    process.env.NEXT_PUBLIC_OIDC_REDIRECT_URI ??
    (typeof window === "undefined" ? "" : `${window.location.origin}/`),
  scope: process.env.NEXT_PUBLIC_OIDC_SCOPE ?? "openid profile offline_access",
};

const encode = (bytes: Uint8Array) =>
  btoa(String.fromCharCode(...bytes))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");

export async function startLogin() {
  if (!config.authority || !config.clientId) throw new Error("OIDC environment is not configured");
  const verifier = encode(crypto.getRandomValues(new Uint8Array(48)));
  const state = encode(crypto.getRandomValues(new Uint8Array(24)));
  const challenge = encode(
    new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier))),
  );
  sessionStorage.setItem("oidc_verifier", verifier);
  sessionStorage.setItem("oidc_state", state);
  const url = new URL(`${config.authority.replace(/\/$/, "")}/authorize`);
  url.search = new URLSearchParams({
    client_id: config.clientId,
    redirect_uri: config.redirectUri,
    response_type: "code",
    scope: config.scope,
    state,
    code_challenge: challenge,
    code_challenge_method: "S256",
  }).toString();
  window.location.assign(url);
}

export async function finishLoginFromCallback() {
  const query = new URLSearchParams(window.location.search);
  const code = query.get("code");
  if (!code) return sessionStorage.getItem("access_token");
  if (query.get("state") !== sessionStorage.getItem("oidc_state")) throw new Error("OIDC state mismatch");
  const response = await fetch(`${config.authority.replace(/\/$/, "")}/oauth/token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "authorization_code",
      client_id: config.clientId,
      redirect_uri: config.redirectUri,
      code_verifier: sessionStorage.getItem("oidc_verifier") ?? "",
      code,
    }),
  });
  if (!response.ok) throw new Error("OIDC token exchange failed");
  const tokens = (await response.json()) as { access_token: string };
  sessionStorage.setItem("access_token", tokens.access_token);
  history.replaceState({}, "", window.location.pathname);
  return tokens.access_token;
}
