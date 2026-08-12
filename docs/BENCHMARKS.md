# Benchmarks

Journal des mesures. **Aucune amélioration n'est revendiquée sans une ligne ici.**

Les cibles ci-dessous sont des objectifs de départ issus du cahier des charges,
pas des résultats. Elles seront révisées après la première mesure réelle.

---

## Latence temps réel

| Date | Appareil | Navigateur | Modèle | Capture | fps p50 | fps p05 | ms/frame p50 | ms/frame p95 | Build |
|---|---|---|---|---|---|---|---|---|---|
| 2026-08-11 | Android 16, GPU annoncé « Samsung Xclipse 920, or similar » | Firefox 153 | `_full` | 720×720 | 22,7 | 18,5 | 41,0 | 50,0 | `49b0c0e` |

**Cible de départ** : ≥ 25 fps, inférence < 50 ms/frame sur téléphone milieu de gamme.

**Statut : première mesure réelle, cible non atteinte de peu.** 22,7 fps contre
25 visés, p50 à 41 ms contre 50 visés — donc sous la cible en débit tout en
restant sous le plafond de latence. Les deux ne se contredisent pas : à 41 ms
d'inférence pour 44 ms de budget par frame, **94 % du temps de frame part dans
le modèle**. Le dessin, la FSM et le reste sont dans le bruit ; le seul levier
utile est le modèle ou la taille d'entrée.

Ce que la mesure établit solidement :

- **Le delegate GPU sert bien.** `GL version: 3.0 … renderer: ANGLE …` puis
  `Graph successfully started running` : pas de repli CPU silencieux.
- **Rien ne s'effondre sur 60 s.** p95 à 50 ms pour un p50 à 41 ms, p05 fps à
  18,5 : distribution serrée, pas de décrochage thermique ni de pic GC.

Ce qu'elle **n'établit pas**, et pourquoi cette ligne reste provisoire :

- **L'appareil n'est pas identifié.** Firefox Android n'expose pas le modèle
  dans son UA, et assainit le renderer WebGL — le `, or similar` est sa
  signature d'approximation. Le Xclipse 920 correspond à un Exynos 2200
  (S22, 2022), pas au S26 attendu. Impossible de trancher depuis ces données.
- **Le navigateur n'est pas celui visé.** Firefox, pas Chrome. Le chemin
  WebGL/WASM de MediaPipe y est différent ; l'écart peut être large.
- **La capture est carrée** (720×720 alors que 1280×720 était demandé), donc
  champ rogné et moins de pixels que prévu — ce qui rend le résultat plutôt
  optimiste, pas pessimiste.

Mesure suivante à faire, dans l'ordre : la même sous Chrome (identifie
l'appareil et donne le chiffre du navigateur cible), puis `?model=lite` sur les
deux. Tant que ces trois lignes n'existent pas, on ne sait pas s'il faut changer
de modèle ou changer de navigateur recommandé.

Procédure : [`PHONE_TESTING.md`](PHONE_TESTING.md).

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
3. Démarrer la caméra, puis **« Mesurer 60 s »**. Les 5 premières secondes sont
   écartées : compilation des shaders et allocation des textures y dominent, et
   les moyenner avec la suite décrit un état où l'appareil n'est jamais.
4. Ouvrir **« Diagnostic »** et capturer le panneau, ou « Copier ».

Le panneau donne p50 et p95 plutôt qu'une moyenne. Un décrochage toutes les
vingt frames est ce que l'athlète perçoit comme un à-coup, et une moyenne
l'efface complètement.

Il donne aussi ce qui rend le chiffre interprétable, et qui n'est visible nulle
part ailleurs sans DevTools :

- la ligne `GL version: … renderer: …` que MediaPipe écrit dans la console au
  démarrage du graphe — **la seule preuve directe** que le delegate GPU a
  effectivement servi, et non un repli CPU silencieux ;
- le renderer que le navigateur déclare, indépendamment de MediaPipe : un écart
  entre les deux est précisément la panne à attraper ;
- la source du modèle (local ou CDN), la résolution réellement obtenue, le
  modèle d'appareil, et le commit du build.

Une ligne de ce tableau sans ces informations n'est pas une mesure.

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
