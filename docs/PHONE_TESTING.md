# Tester depuis le téléphone

`getUserMedia` exige un **contexte sécurisé**. Sur desktop, `localhost` en fait
partie, donc `npm run dev` suffit. Depuis un téléphone, l'adresse LAN
(`http://192.168.x.x:5173`) n'est **pas** un contexte sécurisé : la caméra sera
refusée avant même la demande de permission.

Deux façons de contourner ça. La première est la plus simple et ne demande aucun
certificat.

---

## Option 1 — Port forwarding via Chrome DevTools (Android, recommandé)

Le forwarding fait apparaître le serveur de dev **comme `localhost` sur le
téléphone**, ce qui en fait un contexte sécurisé. Pas de certificat, pas
d'avertissement, et le remote debugging est disponible dans la foulée.

1. Téléphone : Paramètres → À propos → taper 7 fois sur « Numéro de build » pour
   activer les options développeur, puis activer **Débogage USB**.
2. Brancher le téléphone en USB, autoriser le débogage sur le prompt.
3. Sur le PC, lancer le dev server : `cd web && npm run dev`
4. Chrome sur le PC → `chrome://inspect/#devices` → **Port forwarding** →
   ajouter `5173` → `localhost:5173`, cocher « Enable port forwarding ».
5. Sur le téléphone, ouvrir `http://localhost:5173`.

Le backend suit le même chemin : ajouter une règle `8000 → localhost:8000` et
laisser `VITE_API_BASE` sur sa valeur par défaut.

**Bonus** : dans `chrome://inspect`, « inspect » sur l'onglet du téléphone ouvre
les DevTools complets — console, profiler, et surtout le panneau Performance
pour mesurer où passent les millisecondes par frame.

## Option 2 — HTTPS sur le LAN

Utile si le câble n'est pas une option (filmer une traction avec le téléphone
branché en USB n'est pas idéal).

```bash
cd web
npm install -D @vitejs/plugin-basic-ssl
```

Puis dans `vite.config.ts` :

```ts
import basicSsl from "@vitejs/plugin-basic-ssl";

export default defineConfig({
  plugins: [basicSsl()],
  server: { host: true, port: 5173 },
});
```

`npm run dev` sert alors en HTTPS sur l'IP LAN. Le certificat est auto-signé :
Chrome affichera un avertissement à accepter une fois. Le backend doit aussi être
en HTTPS, sinon le navigateur bloquera la requête depuis une page sécurisée
(mixed content) — lancer `uvicorn` avec `--ssl-keyfile` / `--ssl-certfile`, et
pointer `VITE_API_BASE` dessus.

---

## Ce qu'il faut relever

Une fois la PWA ouverte sur le téléphone, le HUD affiche `fps` et `ms / frame`.
Protocole de mesure et tableau à remplir : [`BENCHMARKS.md`](BENCHMARKS.md).

Relever aussi :

- Le **delegate effectif**. `createLandmarker` demande le GPU, mais MediaPipe
  retombe silencieusement sur le CPU si WebGL n'est pas disponible. La console
  (via `chrome://inspect`) le dit au chargement. Une mesure sans cette
  information ne veut rien dire.
- La **variante de modèle**. On charge `pose_landmarker_full`. `_lite` et
  `_heavy` existent et changent complètement le compromis latence/précision.
- Si le téléphone **throttle** : les flagships tiennent 30 s puis descendent en
  fréquence. Laisser tourner 60 s et relever après stabilisation, pas au pic.
