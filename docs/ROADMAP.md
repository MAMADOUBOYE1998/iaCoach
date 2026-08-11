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

## M1 — Comptage traction

- Filtre One-Euro sur l'angle de coude (`web/src/pose/filter.ts`).
- Calibration ROM par athlète au premier usage.
- FSM `idle → eccentric → bottom → concentric → top` sur l'angle de coude,
  seuils exprimés en % de la ROM calibrée.
- Émission de `RepEvent` complets (jamais un compteur nu).
- **Fixtures partagées** : `fixtures/sequences/*.json`, séquences synthétiques
  d'abord (rep propre, rep courte, kipping, occlusion), puis réelles annotées.
- Conformance TS↔Python sur ces fixtures, bloquante en CI.

Sortie mesurée : précision de comptage sur footage propre.

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
