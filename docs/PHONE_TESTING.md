# Tester depuis le téléphone

`getUserMedia` exige un **contexte sécurisé**. Sur desktop, `localhost` en fait
partie, donc `npm run dev` suffit. Depuis un téléphone, l'adresse LAN
(`http://192.168.x.x:5173`) n'est **pas** un contexte sécurisé : la caméra sera
refusée avant même la demande de permission.

Trois façons de contourner ça. **L'option 0 est la seule qui ne demande aucun
ordinateur** — c'est celle à prendre si le téléphone est le seul appareil
disponible.

---

## Option 0 — GitHub Pages (aucun ordinateur requis)

GitHub construit la PWA et la sert en HTTPS, ce qui suffit comme contexte
sécurisé. Le workflow `.github/workflows/pages.yml` fait tout : `npm ci`,
vendoring des assets, build sous le bon sous-chemin, déploiement.

**Rien à activer.** Le site est en ligne :

**https://mamadouboye1998.github.io/iaCoach/**

À chaque commit touchant `web/`, le workflow reconstruit et pousse sur la branche
`gh-pages` ; Pages sert cette branche. Compter une à deux minutes après la fin du
workflow avant que le nouveau contenu soit servi.

### Pourquoi la branche et pas `actions/deploy-pages`

La route officielle (`configure-pages` → `upload-pages-artifact` →
`deploy-pages`) exige que Pages soit configuré avec « Source : GitHub Actions ».
Ce réglage ne peut pas être créé par un workflow — GitHub répond `Create Pages
site failed: Resource not accessible by integration`, et aucune permission
déclarable dans le fichier ne l'autorise. Il n'est pas non plus atteignable
depuis l'app GitHub, qui n'a pas d'écran Pages.

Pousser une branche `gh-pages`, en revanche, active Pages tout seul. C'est la
route retenue : aucune action manuelle, jamais.

La branche est un **artefact**, réécrite en force à chaque déploiement (un seul
commit). Elle contient volontairement le modèle et le runtime WASM que
`.gitignore` exclut de la branche source — sans eux la PWA déployée retomberait
sur un CDN, donc plus de fonctionnement hors-ligne, qui est justement ce qu'on
veut pouvoir tester. Ne rien y éditer à la main.

**Ce qui marche sans backend** : caméra, pose, calibration, comptage, scores,
file d'attente locale des séances. **Ce qui ne marche pas** : le débrief coach,
qui a besoin de l'API — la page l'annonce au lieu de faire semblant. Pour la
mesure fps, c'est sans importance : rien de la boucle temps réel ne dépend du
réseau.

Le site est public, comme le dépôt. Il ne contient aucune clé (la clé Anthropic
vit côté backend, qui n'est pas déployé) et aucune donnée d'entraînement : tout
ce que l'app enregistre reste dans le navigateur du téléphone.

## Option 1 — Port forwarding via Chrome DevTools (Android, avec un PC)

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

Sans ordinateur il n'y a pas de DevTools, donc pas de console — et la console
contient justement ce qui rend une latence interprétable. C'est pourquoi le
panneau **Diagnostic** existe : il capture les lignes de console au vol
(y compris le `GL version: … renderer: …` de MediaPipe, seule preuve directe du
delegate réellement utilisé) et les affiche dans la page.

Une capture d'écran de ce panneau, après « Mesurer 60 s », suffit à remplir une
ligne de `BENCHMARKS.md` **et** à savoir qu'elle est fiable. Le bouton
« Copier » met le même contenu en texte dans le presse-papier, ce qui évite
l'aller-retour par l'image.

### Variante de modèle

`?model=lite` et `?model=full` (défaut) choisissent la taille du réseau, par
exemple `https://mamadouboye1998.github.io/iaCoach/?model=lite`. Les deux sont
embarqués, donc la comparaison se fait hors-ligne comme le reste. `?model=heavy`
existe mais vient du CDN : 29 Mo embarqués pour un point de comparaison que
personne ne relancera n'est pas un marché honnête.

C'est une mesure, pas une préférence : `lite` est plus rapide et moins précis,
et rien d'autre qu'un chiffre sur l'appareil réel ne dit lequel il faut.

### Chrome plutôt que Firefox pour la mesure de référence

Firefox Android n'expose ni le modèle d'appareil dans son UA, ni le vrai
renderer WebGL (il renvoie une approximation, reconnaissable au `, or similar`).
Une ligne de benchmark mesurée sous Firefox ne permet donc pas de dire **sur
quel téléphone** elle a été prise. Le chemin WebGL/WASM de MediaPipe y diffère
aussi de celui de Chrome.

Mesurer sous les deux est utile ; mais la ligne de référence, celle qui décide
si la cible est tenue, se prend sous Chrome.

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
