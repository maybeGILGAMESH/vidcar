const TOKEN_KEY = "access_token";

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

function readToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY) ?? sessionStorage.getItem(TOKEN_KEY);
}

function writeToken(token: string) {
  localStorage.setItem(TOKEN_KEY, token);
  sessionStorage.setItem(TOKEN_KEY, token);
}

export function clearAuth() {
  localStorage.removeItem(TOKEN_KEY);
  sessionStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem("vidcar.demoSession");
}

export async function startLogin() {
  if (!config.authority || !config.clientId) {
    // Local demo without Keycloak: persist a demo session across F5.
    localStorage.setItem("vidcar.demoSession", "1");
    writeToken("demo-local-token");
    return;
  }
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
  if (!code) {
    if (localStorage.getItem("vidcar.demoSession") === "1" && !readToken()) {
      writeToken("demo-local-token");
    }
    return readToken();
  }
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
  writeToken(tokens.access_token);
  history.replaceState({}, "", window.location.pathname);
  return tokens.access_token;
}
