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
   caméra : les cibles fps/latence ne sont pas encore mesurées. `npm run dev`
   puis ouvrir depuis le téléphone — il faut du HTTPS sur le LAN (`vite --https`
   avec un certificat local, ou un tunnel).
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

## M3 — Coaching + persistance

- Persistance SQLite (SQLModel) : athlète, sessions, reps, métriques.
- Base d'exercices structurée (nom, muscles, prérequis, progressions/régressions,
  critères de qualité) + RAG léger.
- Branchement de `POST /coach/debrief` depuis la PWA, avec dégradation propre
  quand `ANTHROPIC_API_KEY` est absente.
- Visualisation de progression (volume, qualité moyenne, PR).

## M4 — Robustesse

- Repli RepNet (comptage par périodicité, agnostique à l'exercice) en validation
  du comptage FSM.
- Jeu de test annoté « footage difficile » : muscle-up, front lever, occlusion,
  contre-jour, angle bas.
- Fine-tuning pose (`vision/finetune/`) : YOLO11-pose vs RTMPose, métriques
  avant/après sur ce jeu de test. Le gagnant sert l'analyse serveur ; le temps
  réel on-device reste MediaPipe pour la latence.

## M5 — Adaptation

- Étage déterministe de bornage (`coach/guardrails.py`) : le LLM propose, le code
  borne volume et progression.
- Programmation adaptative pilotée par les mesures.
- Module running : cadence, régularité, allure, réutilisant la couche capteurs.
