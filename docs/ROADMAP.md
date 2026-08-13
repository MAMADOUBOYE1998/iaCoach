# Roadmap

Chaque jalon se termine par : tests verts, un court README de section, et une
mesure inscrite dans `BENCHMARKS.md` quand le jalon revendique une performance.

---

## M0 — Setup + pose temps réel ✅ livré

- Dépôt structuré, ruff/pytest/vitest/CI en place.
- Contrats Pydantic + export JSON Schema + miroir TypeScript.
- PWA : caméra → MediaPipe Pose Landmarker → overlay squelette.
- Instrumentation fps / ms par frame / confiance, visible à l'écran.
- Angle de coude 3D affiché en direct (vérifie que les `worldLandmarks` sont
  bien lus, avant que la FSM ne s'appuie dessus en M1).

- **Offline-first tenu** : `npm run vendor-assets` vendore le modèle *et* le
  runtime WASM (les deux venaient d'un CDN ; n'en vendorer qu'un ne change
  rien). `resolveAssets()` choisit la source au démarrage et le dit, plutôt que
  d'être figé au build.
- **Service worker** : shell et assets hashés du build mis en cache à
  l'installation, modèle à la première utilisation — 20 Mo forcés en 4G à
  l'installation pour une séance hors-ligne hypothétique n'est pas un marché que
  l'athlète a accepté. Les données d'entraînement ne sont **jamais** mises en
  cache : un débrief périmé servi comme actuel est pire que pas de débrief.
- **Manifeste installable** : icônes générées par script (`npm run make-icons`),
  dessinées dans la zone de sécurité maskable.
- **Choix de caméra** : avant par défaut (se cadrer soi-même demande de voir
  l'aperçu), arrière à un tap, choix mémorisé. Bascule possible en cours de
  séance sans perdre les reps déjà comptées — mais la calibration est invalidée,
  un autre point de vue change l'amplitude mesurée. L'aperçu n'est mis en miroir
  que si la piste **déclare** une caméra frontale : un webcam de portable n'en
  déclare aucune, et deviner casserait un affichage qui marche.

**Reste à faire dans M0, avant de le déclarer clos :**

1. **Mesurer sur un vrai téléphone.** L'environnement de dev ici n'a pas de
   caméra ni de GPU : les cibles fps/latence ne sont pas mesurées.
   `docs/PHONE_TESTING.md` décrit trois chemins, dont un qui ne demande **aucun
   ordinateur** : GitHub Pages construit et sert la PWA en HTTPS, ce qui suffit
   comme contexte sécurisé pour la caméra. Reste une action manuelle, à faire
   depuis le navigateur du téléphone : Settings → Pages → Source « GitHub
   Actions ».

**Vérifié, mais pas mesuré** : `web/scripts/smoke.mjs` fait tourner la chaîne
complète dans un Chromium headless avec caméra factice — service worker installé
et périmètre correct, aucun tiers contacté, rechargement réseau coupé qui
exécute réellement le bundle (et pas seulement le HTML statique). Ses chiffres de
latence viennent d'un rasteriseur logiciel et ne transposent pas : voir
`BENCHMARKS.md`.

Trois défauts trouvés par ce test, qui ne se voyaient dans aucun test unitaire :

0. **Le mode hors-ligne était mort en silence sous sous-chemin.** Le serveur
   renvoie `Vary: Origin` sur les fichiers statiques ; les requêtes de precache
   émises par le worker ne portent pas le même `Origin` que celles du `<script>`
   de la page, donc `cache.match` échouait à chaque fois. Le fichier était bien
   en cache, l'inspection le confirmait, et la requête partait quand même sur le
   réseau. Recherche faite en ignorant `Vary` — tout ce qui est mis en cache est
   un fichier statique adressé par son hash, sans négociation de contenu.


1. La latence d'inférence n'était accumulée que sur les frames où une pose est
   trouvée. Une frame vide coûte pourtant une inférence complète : la moyenne
   affichée excluait silencieusement chaque instant où l'athlète sort du cadre.
   `detect()` renvoie maintenant le coût dans tous les cas.
2. L'URL CDN du runtime WASM était figée sur `0.10.18` alors que npm avait
   installé `0.10.35`. Elle est désormais injectée au build depuis la version
   réellement installée.

## M1 — Comptage traction ✅ livré

- Filtre One-Euro sur l'angle de coude, en TS et en Python.
- Calibration ROM par athlète (`CalibrationRecorder`), qui **refuse de calibrer**
  si l'amplitude est trop faible ou le suivi trop instable — une mauvaise
  calibration corrompt silencieusement tous les scores suivants.
- FSM `idle → bottom → concentric → top → eccentric` sur l'angle de coude, avec
  hystérésis sur chaque frontière, seuils en % de la ROM calibrée.
- `RepEvent` complets, avec les cinq scores continus. Une rep trop courte est
  **enregistrée** avec `counted=false`, jamais jetée.
- Confiance basse → seul `low_confidence` est remonté, les corrections sont
  supprimées.
- 8 fixtures partagées (`fixtures/sequences/`) + golden streams
  (`fixtures/golden/`). Conformance TS↔Python bloquante en CI : les deux
  implémentations produisent des `RepEvent` identiques à 1e-9 près.
- PWA : calibration puis comptage en direct, avec retour par rep.

**Dette assumée, à traiter en M2 :**

1. `tempo_control` reste bruité sur les reps de faible amplitude (0,63 vs 0,76
   sur deux reps identiques dans `short_rom_3_reps`). L'écart ne change aucun
   flag aujourd'hui, mais la métrique est trop sensible au jitter pour être
   montrée telle quelle à l'athlète.
2. `kip_tolerance_ms = 0.80 m/s` et `trunk_tolerance_deg = 30°` sont des
   placeholders. Ils tiennent sur les fixtures synthétiques ; il faut les
   recaler sur des vidéos réelles annotées.
3. Les fixtures sont **synthétiques**. Elles verrouillent le comportement et la
   conformance, mais ne disent rien de la précision sur du vrai footage — c'est
   la mesure qui manque, et elle vient avec les clips réels.
4. **Les fixtures tournent à 30 fps, l'appareil à 21.** Mesuré, pas supposé
   (`BENCHMARKS.md`). À 47 ms par frame, la fenêtre de dérivation de 100 ms
   s'étire en pratique jusqu'à 148 ms et lisse les pics de vitesse angulaire —
   exactement le signal que `kip_tolerance_ms` et `tempo_control` exploitent.
   Ces deux-là liront donc **bas** sur le téléphone. Le recalage se fait sur
   clips réels enregistrés au débit réel de l'appareil, pas en ajustant la
   constante à l'aveugle.

Sortie mesurée : précision de comptage sur footage propre. **Non mesurée** —
bloquée sur l'acquisition de clips annotés.

## Évaluation hors-ligne (préalable à M2/M4) ✅ livré

Le blocage « clips annotés » n'était pas la disponibilité des données : c'était
que rien ici ne savait transformer une vidéo en `RepEvent`.

- `iacoach.frame` — `FrameSampler` et `CalibrationRecorder` portés en Python,
  miroirs du TypeScript. Conformance bloquante en CI sur
  `fixtures/landmarks/`, au niveau des landmarks cette fois, pas des
  `FrameSample` : c'est la géométrie elle-même qui est verrouillée.
- `vision/eval/evaluate.py` — vidéo → MediaPipe → `FrameSample` → `RepCounter`,
  puis MAE / OBO / MAPE, les métriques de la littérature sur le comptage.
- `iacoach.evaluation` — la logique de métrique, testée : un clip non évaluable
  part dans `skipped`, jamais dans les résultats comme un zéro.

Ce qui reste vrai et qu'aucune base publique ne réglera : les scores de qualité
sont définis **relativement à l'amplitude calibrée de l'athlète**, et une base
publique n'a pas de calibration par sujet. Le harnais l'estime depuis le clip,
ce qui flatte le résultat. Détail et sources utilisables :
[`DATASETS.md`](DATASETS.md).

## M2 — Qualité fine + classifieur

**Classifieur d'exercice — livré, spécificité à mesurer.**

`iacoach.classify` + `web/src/analysis/classify.ts`, conformance bloquante sur
`fixtures/classify/` (7 scénarios, dont 2 refus).

Justification chiffrée, pas esthétique : sur 100 clips d'autres mouvements, le
compteur a inventé des reps sur 31. Il compte des cycles de flexion du coude, et
ramer en est un. Rien en amont ne demandait si l'athlète faisait l'exercice.

- Fenêtre glissante de 2 s → posture (mains/épaules, verticalité du tronc) et
  travail (amplitude coude vs genou) → score continu par exercice.
- `UNKNOWN` est une réponse de premier rang, pas un échec. Un jeu de règles mal
  routé corrige la mauvaise chose, ce qui est pire que ne pas corriger.
- Hystérésis sur le label lui-même : un challenger doit gagner de 0,15 sur 3
  fenêtres consécutives. Une étiquette qui clignote en pleine série est pire
  qu'une étiquette périmée.
- Tous les seuils sont des fractions des longueurs de segments de l'athlète.
  Aucun mètre absolu ; un test vérifie qu'un athlète 1,3× plus grand donne les
  mêmes nombres.

**Non émis délibérément**, et écrit dans le code plutôt qu'absent en silence :
`chin_up` (la supination de prise n'est pas récupérable de ces landmarks) et
`muscle_up` (demande un modèle de transition, et zéro exemple annoté — une
muscle-up sera lue `pull_up` pendant sa phase de traction).

**Statut des seuils : priors géométriques, pas mesures.** Ils encodent ce que
*sont* les postures. Ils n'ont été ajustés sur aucun positif annoté, faute
d'en avoir. À traiter comme `kip_tolerance_ms`.

Reste dans M2 :

- Faire tourner la spécificité sur les 100 clips QUVA : le harnais rapporte
  maintenant `false_positive_clips_after_gate` et `reps_invented_after_gate`.
  C'est la seule mesure que ce jeu permet — il n'a pas de positifs exploitables.
- Traduction des `flags` en retours actionnables en français.
- Recalage de `kip_tolerance_ms` et `trunk_tolerance_deg` sur footage réel
  enregistré au débit réel de l'appareil (~21 fps, pas 30).

Sortie mesurée : spécificité après portillon sur QUVA. La sensibilité reste
non mesurable sur données publiques.

## M3 — Coaching + persistance ✅ livré

- Persistance SQLite (`sqlite3` nu, pas d'ORM) : athlète, sessions, reps,
  débriefs. Les reps sont stockées en colonnes, pas en blob — « amplitude moyenne
  par semaine » est une requête SQL, pas une boucle Python.
- Base d'exercices structurée (19 entrées) + retrieval déterministe par règles.
  Le coach reçoit un sous-ensemble du catalogue réel plutôt que carte blanche
  pour inventer des noms de mouvements.
- API : athlètes, sessions, progression, débrief. Le débrief est mis en cache par
  séance — rouvrir une séance passée ne refacture pas l'API.
- PWA : enregistrement de séance, file d'attente hors-ligne, débrief affiché,
  courbe de progression (meilleure rep vs moyenne).
- Dégradation propre : sans backend, la séance est mise en file et resynchronisée
  plus tard ; sans `ANTHROPIC_API_KEY`, tout marche sauf le débrief.

**Dette assumée :**

1. Aucune authentification. Un `athlete_id` par appareil, pas de compte. Suffisant
   pour l'usage solo visé ; à revoir avant toute exposition réseau.
2. Le retrieval est un score de tags. Ça suffit à 19 entrées ; au-delà de ~100 il
   faudra autre chose.
3. La courbe ne montre que l'amplitude. Volume, tempo et fatigue sont en base
   mais pas encore tracés.

## M4 — Robustesse

- Repli RepNet (comptage par périodicité, agnostique à l'exercice) en validation
  du comptage FSM.
- Jeu de test annoté « footage difficile » : muscle-up, front lever, occlusion,
  contre-jour, angle bas.
- Fine-tuning pose (`vision/finetune/`) : YOLO11-pose vs RTMPose, métriques
  avant/après sur ce jeu de test. Le gagnant sert l'analyse serveur ; le temps
  réel on-device reste MediaPipe pour la latence.

## M5 — Adaptation ✅ livré

- **Étage déterministe de bornage.** `planning.py` calcule la charge (ratio
  aigu/chronique sur 7 j / 28 j, tendance de la qualité technique) et en déduit
  des bornes ; `coach/guardrails.py` y tient la réponse du modèle. Le LLM
  propose, le code décide. L'invariant n'est plus une phrase dans un prompt.
- Les bornes sont **données au modèle à l'avance** puis réappliquées après : une
  séance conçue dans les clous est cohérente, une séance rognée après coup ne
  l'est pas.
- Chaque correction est un `GuardrailAdjustment` affiché à l'athlète. Un plafond
  silencieux est indiscernable d'un bug.
- Seul le brut du modèle est mis en cache : resserrer une borne agit aussi sur
  les débriefs passés.
- **Module running** : cadence, régularité et allure — depuis l'accéléromètre et
  le GPS, **pas la caméra** (voir ci-dessous).

**Décisions et limites :**

1. Croissance de volume plafonnée à **+10 % par séance**, quoi qu'il arrive. Le
   ratio aigu/chronique peut justifier de maintenir, jamais de dépasser ce
   plafond.
2. Le ratio n'est **pas calculé** en dessous de 4 séances sur 28 jours. Un ratio
   tiré de trois jours de données est un nombre, pas un signal.
3. La notation `NxM` est parsée pour vérifier le volume ; `3x30s` (gainage) et
   `AMRAP` ne le sont pas et sont signalés comme non vérifiés plutôt que devinés.
   Une fourchette `3x8-10` est lue à sa borne **haute** : ce chiffre alimente un
   plafond de sécurité.
4. L'ACWR est une heuristique à la littérature contestée. Elle est utilisée ici
   comme **frein**, jamais comme autorisation de pousser.
5. Le running n'est **ni persisté ni coaché** : c'est un module de mesure
   autonome et testé, pas encore branché sur les contrats partagés. Le brancher
   sans données réelles reviendrait à figer des seuils inventés.
6. `REGULARITY_TOLERANCE` et `DEFAULT_PEAK_THRESHOLD` sont calibrés sur signal
   synthétique uniquement. À recaler sur des courses enregistrées avant
   d'afficher une cadence comme un fait.

### Pourquoi le running n'utilise pas la caméra

Le cahier des charges dit « en réutilisant la couche capteurs/vision quand
pertinent ». Pour la course, la vision ne l'est pas : se filmer en courant
demande une seconde personne ou un trépied fixe qu'on quitte en courant — ce qui
décrit une séance de piste, pas une sortie. Le téléphone est déjà sur l'athlète
et son accéléromètre mesure la foulée directement.

La caméra redevient pertinente pour des **éducatifs de course filmés sur place**.
C'est un module ultérieur, pas celui-ci.
