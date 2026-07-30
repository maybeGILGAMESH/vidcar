import { useEffect, useMemo, useState } from "react";
import { Button, SafeAreaView, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import MapView, { Marker } from "react-native-maps";
import * as Location from "expo-location";
import * as ImagePicker from "expo-image-picker";
import * as SecureStore from "expo-secure-store";
import * as WebBrowser from "expo-web-browser";
import * as AuthSession from "expo-auth-session";
import { ApiClient, GeoPoint, ProcessingResult } from "@vidcar/api-client";
import { QueuedUpload, ResumableUploadQueue } from "./src/uploadQueue";

WebBrowser.maybeCompleteAuthSession();
const authority = process.env.EXPO_PUBLIC_OIDC_AUTHORITY ?? "https://identity.example.invalid";
const clientId = process.env.EXPO_PUBLIC_OIDC_CLIENT_ID ?? "vidcar-mobile";
const redirectUri = AuthSession.makeRedirectUri({ scheme: "vidcar" });
const discovery = {
  authorizationEndpoint: `${authority.replace(/\/$/, "")}/authorize`,
  tokenEndpoint: `${authority.replace(/\/$/, "")}/oauth/token`,
};

export default function App() {
  const [request, response, promptAsync] = AuthSession.useAuthRequest(
    { clientId, redirectUri, scopes: ["openid", "profile", "offline_access"], usePKCE: true },
    discovery,
  );
  const [position, setPosition] = useState<GeoPoint>();
  const [title, setTitle] = useState("");
  const [notes, setNotes] = useState([""]);
  const [assets, setAssets] = useState<ImagePicker.ImagePickerAsset[]>([]);
  const [queueItems, setQueueItems] = useState<QueuedUpload[]>([]);
  const [results, setResults] = useState<ProcessingResult[]>([]);
  const [message, setMessage] = useState("Готово");

  const api = useMemo(
    () =>
      new ApiClient(process.env.EXPO_PUBLIC_API_URL ?? "http://localhost:8000", () =>
        SecureStore.getItemAsync("vidcar_access_token"),
      ),
    [],
  );

  const queue = useMemo(() => {
    const blobs = new Map<string, Blob>();
    return new ResumableUploadQueue(api, async (uri, url, partNumber, partSize, fileSize) => {
      let blob = blobs.get(uri);
      if (!blob) {
        blob = await (await fetch(uri)).blob();
        blobs.set(uri, blob);
      }
      const start = (partNumber - 1) * partSize;
      const upload = await fetch(url, {
        method: "PUT",
        body: blob.slice(start, Math.min(start + partSize, fileSize)),
      });
      const etag = upload.headers.get("etag");
      if (!upload.ok || !etag) throw new Error(`Не удалось загрузить часть ${partNumber}`);
      return etag;
    });
  }, [api]);

  useEffect(() => {
    queue.restore().then(setQueueItems);
  }, [queue]);

  useEffect(() => {
    if (response?.type === "success") {
      const code = response.params.code;
      if (!code || !request?.codeVerifier) return;
      AuthSession.exchangeCodeAsync(
        { clientId, code, redirectUri, extraParams: { code_verifier: request.codeVerifier } },
        discovery,
      )
        .then((tokens) => SecureStore.setItemAsync("vidcar_access_token", tokens.accessToken))
        .then(() => setMessage("Вход выполнен"))
        .catch((error: Error) => setMessage(error.message));
    }
  }, [request, response]);

  const locate = async () => {
    const permission = await Location.requestForegroundPermissionsAsync();
    if (!permission.granted) return setMessage("Нет разрешения на геолокацию");
    const location = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Highest });
    const heading = location.coords.heading;
    setPosition({
      latitude: location.coords.latitude,
      longitude: location.coords.longitude,
      accuracyMeters: location.coords.accuracy ?? undefined,
      bearingDegrees: heading != null && heading >= 0 ? heading : undefined,
    });
  };

  const pickVideos = async () => {
    const selected = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ImagePicker.MediaTypeOptions.Videos,
      allowsMultipleSelection: true,
      quality: 1,
    });
    if (!selected.canceled) setAssets(selected.assets);
  };

  const submit = async () => {
    if (!position || !assets.length) return setMessage("Нужны GPS и видео");
    try {
      const survey = await api.createSurvey({
        title,
        observedAt: new Date().toISOString(),
        location: position,
        notes: notes.filter(Boolean).map((text) => ({ text })),
      });
      for (const asset of assets) {
        await queue.enqueue({
          surveyId: survey.id,
          uri: asset.uri,
          fileName: asset.fileName ?? `video-${Date.now()}.mp4`,
          size: asset.fileSize ?? 0,
          contentType: asset.mimeType ?? "video/mp4",
        });
      }
      const completed = await queue.run(setQueueItems);
      const statuses = await Promise.all(
        completed
          .filter((item) => item.session)
          .map((item) => api.getProcessingResult(item.session!.videoId)),
      );
      setResults(statuses);
      setMessage("Очередь передана в обработку");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Ошибка");
    }
  };

  const refresh = async () => {
    setResults(await Promise.all(results.map((result) => api.getProcessingResult(result.videoId))));
  };

  return (
    <SafeAreaView style={styles.safe}>
      <ScrollView contentContainerStyle={styles.page}>
        <View style={styles.header}>
          <Text style={styles.brand}>VIDCAR</Text>
          <Button title="Войти OIDC" disabled={!request} onPress={() => promptAsync()} />
        </View>
        <MapView
          style={styles.map}
          region={position ? { ...position, latitudeDelta: 0.01, longitudeDelta: 0.01 } : undefined}
        >
          {position && <Marker coordinate={position} />}
        </MapView>
        <Button title="Получить точный GPS" onPress={locate} />
        {position && (
          <Text style={styles.muted}>
            {position.latitude.toFixed(6)}, {position.longitude.toFixed(6)} · ±
            {Math.round(position.accuracyMeters ?? 0)} м ·{" "}
            {position.bearingDegrees == null ? "направление н/д" : `${Math.round(position.bearingDegrees)}°`}
          </Text>
        )}
        <Text style={styles.title}>Новое обследование</Text>
        <TextInput style={styles.input} value={title} onChangeText={setTitle} placeholder="Название" />
        <Button title={`Выбрать видео (${assets.length})`} onPress={pickVideos} />
        <View style={styles.notes}>
          <Text>Заметки {notes.length}/10</Text>
          {notes.map((note, index) => (
            <View style={styles.note} key={index}>
              <TextInput
                style={[styles.input, styles.grow]}
                value={note}
                maxLength={500}
                onChangeText={(text) => setNotes(notes.map((value, i) => (i === index ? text : value)))}
                placeholder={`Заметка ${index + 1}`}
              />
              {notes.length > 1 && <Button title="×" onPress={() => setNotes(notes.filter((_, i) => i !== index))} />}
            </View>
          ))}
          {notes.length < 10 && <Button title="+ Заметка" onPress={() => setNotes([...notes, ""])} />}
        </View>
        <Button title="Создать и загрузить" onPress={submit} />
        <Text style={styles.message}>{message}</Text>
        {queueItems.map((item) => <Text key={item.id}>{item.fileName}: {item.status} ({item.completedParts.length})</Text>)}
        {results.length > 0 && <Button title="Обновить статусы" onPress={refresh} />}
        {results.map((result) => (
          <Text key={result.videoId}>{result.videoId}: {result.status}{result.downloadUrl ? ` · ${result.downloadUrl}` : ""}</Text>
        ))}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: "#f4f6f3" },
  page: { padding: 16, gap: 12 },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  brand: { color: "#ef5b25", fontSize: 24, fontWeight: "800" },
  map: { height: 280, borderRadius: 16 },
  title: { fontSize: 24, fontWeight: "700", marginTop: 8 },
  input: { backgroundColor: "white", borderColor: "#cdd5d0", borderWidth: 1, borderRadius: 9, padding: 12 },
  notes: { gap: 8 },
  note: { flexDirection: "row", alignItems: "center", gap: 6 },
  grow: { flex: 1 },
  muted: { color: "#64716c" },
  message: { color: "#173f35", fontWeight: "600" },
});
