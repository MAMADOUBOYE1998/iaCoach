# Benchmarks

Journal des mesures. **Aucune amélioration n'est revendiquée sans une ligne ici.**

Les cibles ci-dessous sont des objectifs de départ issus du cahier des charges,
pas des résultats. Elles seront révisées après la première mesure réelle.

---

## Latence temps réel

| Date | Appareil | Modèle pose | fps moyen | ms/frame (p50) | ms/frame (p95) |
|---|---|---|---|---|---|
| — | — | — | — | — | — |

**Cible de départ** : ≥ 25 fps, inférence < 50 ms/frame sur téléphone milieu de gamme.

**Statut : non mesuré.** L'environnement de développement de ce dépôt n'a pas de
caméra. Le M0 instrumente fps et latence à l'écran ; il faut ouvrir la PWA depuis
un vrai téléphone pour remplir ce tableau. Procédure :
[`PHONE_TESTING.md`](PHONE_TESTING.md).

> ⚠️ **Le Galaxy S26 (SM-S942B/DS) ne valide pas la cible.** La cible de départ
> est « ≥ 25 fps sur téléphone **milieu de gamme** ». Un flagship 2026 devrait
> l'atteindre largement — s'il ne l'atteint pas, c'est un signal d'alarme, mais
> l'atteindre ne prouve rien sur le milieu de gamme.
>
> Ce que la mesure sur S26 établit réellement : que le pipeline tient en
> conditions réelles, quel est le plafond de performance, et où passe le temps.
> Pour la cible milieu de gamme, il faudra soit un second appareil, soit un
> throttling CPU volontaire dans DevTools (4× ou 6× slowdown) comme approximation
> — approximation à documenter comme telle, pas à faire passer pour une mesure.

### Ce qui a été vérifié en CI-like, et qui n'est pas un benchmark

`web/scripts/smoke.mjs` fait tourner la chaîne complète dans un Chromium headless
avec une caméra factice. Il établit que le pipeline s'exécute de bout en bout
(runtime WASM, modèle, boucle d'inférence, service worker, rechargement
hors-ligne). Les chiffres qu'il affiche viennent d'un **rasteriseur logiciel**
(SwiftShader, aucun GPU) :

| Date | Machine | fps | ms/frame |
|---|---|---|---|
| 2026-08-11 | conteneur headless, SwiftShader | 4 | ~990 |

Deux ordres de grandeur au-dessus de la cible, et c'est attendu : sans GPU,
BlazePose tourne intégralement sur CPU en WASM. **Ce chiffre ne dit rien d'un
téléphone** et n'a pas sa place dans le tableau ci-dessus. Il sert uniquement de
plancher : si le pipeline ne tournait pas du tout, ce test le dirait.

**Protocole** (à appliquer identiquement à chaque mesure) :
1. Téléphone en charge, luminosité fixe, application seule au premier plan.
2. Sujet cadré en pied, 2–3 m de la caméra, éclairage intérieur constant.
3. Laisser tourner 60 s, relever la moyenne affichée après stabilisation.
4. Noter le modèle exact (`pose_landmarker_lite` / `_full` / `_heavy`) et le
   delegate effectif (GPU ou repli CPU).

## Précision de comptage — footage propre

| Date | Jeu de test | Reps réelles | Détectées | Précision | Rappel |
|---|---|---|---|---|---|
| — | — | — | — | — | — |

**Cible de départ** : > 95 %. Mesurable à partir de M1.

## Robustesse — footage difficile

| Date | Sous-ensemble | Reps réelles | Détectées | Score | Notes |
|---|---|---|---|---|---|
| — | — | — | — | — | — |

Sous-ensembles prévus : muscle-up, front lever, occlusion partielle,
contre-jour, angle bas. Mesurable à partir de M4.

## Fine-tuning pose — avant / après

| Date | Modèle | Dataset | mAP / OKS avant | après | Delta |
|---|---|---|---|---|---|
| — | — | — | — | — | — |

Comparaison YOLO11-pose vs RTMPose sur le même jeu de test annoté. C'est cette
mesure, et pas une préférence a priori, qui tranche le choix du modèle serveur.

## Coût coaching

| Date | Modèle | Tokens in | out | cache read | Coût/séance |
|---|---|---|---|---|---|
| — | — | — | — | — | — |

Le system prompt porte un point de cache ; `cache_read_input_tokens` à zéro sur
des appels répétés signale un invalidateur silencieux dans l'assemblage du prompt.
