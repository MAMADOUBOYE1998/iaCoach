# iaCoach — Architecture (proposition à valider)

Statut : **proposition**. Le M0 est implémenté pour valider la stack sur du réel ;
M1+ attend ta validation de ce document.

---

## 1. Décisions de stack (et pourquoi)

| Couche | Choix | Justification | Alternative écartée |
|---|---|---|---|
| Temps réel on-device | PWA TypeScript + `@mediapipe/tasks-vision` (Pose Landmarker, BlazePose 33 kp) | Accès caméra sans build natif, cross-plateforme, WASM+GPU delegate, `worldLandmarks` 3D métriques exposés | MoveNet Thunder (TF.js) : 17 kp seulement, pas de 3D métrique → insuffisant pour ROM/symétrie |
| Build web | Vite + TS strict | Démarrage < 1s, HTTPS local trivial (obligatoire pour `getUserMedia`) | Next.js : SSR inutile ici, alourdit le chemin critique caméra |
| Analyse serveur (clips) | Python + Ultralytics YOLO11-pose, puis RTMPose si le benchmark le justifie | YOLO11-pose : pipeline d'entraînement le plus court à mettre en place (dataset COCO-pose format, `model.train()`), export ONNX/TensorRT | MMPose/RTMPose d'abord : meilleure précision annoncée mais toolchain OpenMMLab plus lourde. **Décision : benchmarker les deux en M4, trancher sur données.** |
| Backend | Python 3.11 + FastAPI + Pydantic v2 | Contrats stricts partagés Python↔TS via JSON Schema généré | Node/Express : perdrait la co-localisation avec le code vision PyTorch |
| Persistance | SQLite (WAL) via SQLModel en v1 | Mono-utilisateur, zéro ops, fichier unique sauvegardable | Postgres : prévu en option prod, schéma compatible (`athlete_id` partout) |
| LLM | API Anthropic Messages, `claude-sonnet-5` par défaut | Coût/latence sur le débrief de séance | — |

### Contrainte de latence assumée

Le comptage et la qualité tournent **entièrement dans le navigateur**. Aucun appel
réseau dans la boucle `requestAnimationFrame`. La fenêtre de correction utile est
~100 ms ; un aller-retour cloud coûte 150–400 ms. Le backend ne sert que
l'asynchrone : persistance, coaching LLM, analyse de clips uploadés.

---

## 2. Le point dur : une seule logique métier, deux runtimes

La FSM de comptage et les métriques qualité doivent tourner **en TS on-device**
(temps réel) **et en Python côté serveur** (analyse de clips, évaluation,
régression sur le jeu de test). C'est le piège classique : deux implémentations
qui divergent silencieusement.

Trois options évaluées :

1. **TS seul, Python appelle Node en sous-process** — rejeté : fragilise le
   pipeline d'évaluation, casse la parallélisation des benchmarks.
2. **Python seul, compilé WASM via Pyodide** — rejeté pour la v1 : ~2 s de
   démarrage, coût par frame incompatible avec la cible 25 fps.
3. **Double implémentation + conformance tests sur fixtures partagées** —
   **retenu**.

Concrètement : `fixtures/sequences/*.json` contient des séquences de keypoints
(synthétiques et réelles annotées). Chaque implémentation doit produire des
`RepEvent` identiques à une tolérance près. Le test tourne dans `pytest` **et**
dans `vitest`, sur les mêmes fichiers. Une divergence casse la CI.

C'est la seule option qui rend la divergence *détectable* plutôt qu'invisible.

---

## 3. Contrat central : `RepEvent`

**Invariant** : une rep ne produit jamais un simple `count += 1`. Elle produit un
`RepEvent` complet. Tout le reste (fatigue, progression, périodisation, coach LLM)
se construit dessus. Voir `backend/src/iacoach/contracts.py` (source de vérité) et
`contracts/schema/` (JSON Schema généré, consommé par le front).

Principes non négociables :

1. **Tous les calculs biomécaniques utilisent `worldLandmarks` (3D, mètres)**,
   jamais les landmarks normalisés 2D. Le 2D dépend du cadrage et de la distance
   caméra ; le ROM calculé dessus n'est pas comparable d'une séance à l'autre.
2. **Les scores de forme sont continus dans `[0,1]`**, jamais booléens. Une règle
   retourne une magnitude d'écart normalisée. « Rep OK/KO » est précisément ce que
   ce projet doit dépasser.
3. **Aucun landmark sous `visibility >= 0.6` n'est utilisé pour une correction.**
   Une correction fausse est pire qu'aucune correction. Le champ
   `RepEvent.confidence` porte la proportion de frames exploitables.
4. **Seuils exprimés en % de la ROM personnelle**, calibrée au premier usage — pas
   d'angles fixes en dur. Un athlète de 1,60 m et un de 1,95 m n'ont pas la même
   géométrie de traction.

### Filtrage du signal

Moyenne glissante **interdite** : elle ajoute ~80 ms de retard et écrase les pics
de vitesse angulaire, qui sont le signal de fatigue principal. On utilise un
**filtre One-Euro** (implémenté en M1, `web/src/pose/filter.ts`), qui adapte sa
coupure à la vitesse du signal.

---

## 4. Arborescence

```
iaCoach/
├── docs/            ARCHITECTURE.md, ROADMAP.md, BENCHMARKS.md
├── prompts/         coaching.md — system prompt versionné
├── contracts/schema/  JSON Schema générés depuis Pydantic (ne pas éditer)
├── fixtures/        séquences de keypoints annotées (conformance TS↔Python)
├── backend/
│   ├── src/iacoach/
│   │   ├── contracts.py    ← source de vérité des contrats
│   │   ├── geometry.py     angles 3D, utilitaires
│   │   ├── config.py       env, jamais de secret en dur
│   │   ├── coach/          client Anthropic + assemblage du prompt
│   │   ├── api/            FastAPI
│   │   └── scripts/        export_schemas.py
│   └── tests/
├── web/             PWA : caméra, pose temps réel, comptage, UI
│   └── src/{pose,analysis,ui,types}
└── vision/finetune/ pipeline PC/RTX : dataset, entraînement, métriques avant/après
```

---

## 5. Confidentialité

- **Aucune image ni vidéo ne quitte l'appareil par défaut.** Seules les features
  numériques agrégées (`SessionSummary`) partent vers l'API Anthropic.
- Les clips d'entraînement du dataset vision sont traités comme données sensibles :
  restent sur le PC local, jamais commités.
- Mode 100 % local documenté : sans `ANTHROPIC_API_KEY`, l'app fonctionne
  intégralement sauf le débrief coach.
- Clé API via variable d'environnement uniquement. `.env` est gitignored.

---

## 6. Couche coaching — écart assumé avec le brief

Le brief demande « le LLM répond en JSON pur, sans préambule, parsé de façon
défensive ». On fait mieux : l'API Anthropic expose des **structured outputs**
(`output_config.format` + JSON Schema). Le format est contraint côté serveur, pas
demandé poliment dans le prompt. On utilise `client.messages.parse()` avec le
modèle Pydantic → objet validé, zéro parsing défensif, zéro retry sur préambule.

Deux garde-fous supplémentaires :

- **Le LLM ne décide jamais de la charge.** Il lit les métriques et propose ;
  l'étage déterministe (`coach/guardrails.py`, M5) borne volume et progression
  avant que ça atteigne l'utilisateur.
- Le system prompt (`prompts/coaching.md`) interdit tout conseil médical et
  renvoie vers un professionnel en cas de douleur.

Modèles : `claude-sonnet-5` par défaut (débrief de séance), `claude-opus-4-8` pour
la planification hebdomadaire. Ces deux IDs sont ceux du brief et sont valides.
`claude-opus-5` est également disponible et remplacerait avantageusement
`claude-opus-4-8` sur la planification — à trancher au premier benchmark coût.

---

## 7. Ce qui doit être meilleur, et comment on le prouve

| Axe | Cible de départ | Mesure | Où |
|---|---|---|---|
| Latence | ≥ 25 fps, inférence < 50 ms/frame, tel milieu de gamme | Compteur fps intégré + `performance.now()` par frame | M0 (déjà instrumenté) |
| Précision comptage | > 95 % sur footage propre | reps détectées vs annotation manuelle | M1 |
| Robustesse | Score sur footage difficile (muscle-up, occlusion, contre-jour) | même métrique, jeu de test séparé | M4 |
| Qualité fine | Retour actionnable, pas binaire | accord avec annotation experte par défaut | M2 |
| Adaptation | Programmation issue des mesures | A/B contre table statique | M5 |

Ces chiffres sont des **objectifs de départ**, à réviser après le premier
benchmark réel. `docs/BENCHMARKS.md` tient le journal des mesures.

---

## 8. Risques identifiés

| Risque | Impact | Mitigation |
|---|---|---|
| MediaPipe décroche sur muscle-up / corps inversé | Cœur du produit | Repli RepNet (périodicité, agnostique à la pose) + fine-tuning M4. Le décrochage est *détecté* via `confidence`, pas subi silencieusement. |
| Divergence TS↔Python | Bugs invisibles | Conformance tests sur fixtures partagées, bloquants en CI |
| Dataset trop petit pour le fine-tuning | M4 sans gain | Annotation semi-auto (gros modèle → correction manuelle), viser 2–3k frames sur postures difficiles avant d'entraîner |
| Calibration mal faite → seuils absurdes | Feedback faux | Bornes physiologiques dures autour de la ROM calibrée ; refus de calibrer si `confidence` insuffisante |
| PWA iOS : contraintes caméra Safari | Bloque une plateforme | Testé en M0 ; repli React Native envisagé en v2 |

---

## 9. Questions ouvertes (réponse attendue avant M1)

1. **Convergence avec `fitai-v2` ?** Le contexte projet `fitai` décrit un projet
   très proche (même domaine, mêmes invariants, stack Next.js + Postgres/Timescale
   + Polar H10). iaCoach est-il un redémarrage volontaire sur une stack plus
   légère, ou faut-il converger ? J'ai repris les invariants durement acquis
   (worldLandmarks, RepEvent, scoring continu, Kalman/One-Euro, calibration
   par utilisateur) et gardé la stack du brief présent.
2. **Capteurs** : le brief ne mentionne pas le cardio. On garde une interface
   capteur générique (`sensors/`) sans l'implémenter, ou hors périmètre total ?
3. **Cible de déploiement** : usage perso strict, ou plusieurs athlètes ? Le schéma
   porte `athlete_id` partout dans les deux cas, mais l'auth change.
