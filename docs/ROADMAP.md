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

**Reste à faire dans M0, avant de le déclarer clos :**

1. **Mesurer sur un vrai téléphone.** L'environnement de dev ici n'a pas de
   caméra : les cibles fps/latence ne sont pas encore mesurées. Procédure
   complète dans `docs/PHONE_TESTING.md` (port forwarding Chrome DevTools : pas
   de certificat à gérer).
2. **Vendorer le modèle** (`npm run fetch-model`) pour tenir la promesse
   offline-first. Aujourd'hui le `.task` vient d'un CDN.
3. **Service worker** pour le cache d'app shell.

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

Sortie mesurée : précision de comptage sur footage propre. **Non mesurée** —
bloquée sur l'acquisition de clips annotés.

## M2 — Qualité fine + classifieur

- ROM, kipping (accélération du bassin orthogonale à l'axe), symétrie, tempo,
  alignement — tous continus dans `[0,1]`.
- Traduction des `flags` en retours actionnables en français.
- Classifieur d'exercice : fenêtre glissante de keypoints → exercice, pour
  router vers les bonnes règles.

Sortie mesurée : accord avec annotation experte sur le jeu de test.

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
