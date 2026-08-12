# Benchmarks

Journal des mesures. **Aucune amélioration n'est revendiquée sans une ligne ici.**

Les cibles ci-dessous sont des objectifs de départ issus du cahier des charges,
pas des résultats. Elles seront révisées après la première mesure réelle.

---

## Latence temps réel

| Date | Appareil | Navigateur | Modèle | Capture | fps p50 | fps p05 | ms/frame p50 | ms/frame p95 | Build |
|---|---|---|---|---|---|---|---|---|---|
| 2026-08-11 | Xclipse 960 (Galaxy S26) | Chrome 151 | `_full` | 720×1280 | 21,3 | 17,5 | 44,1 | 53,5 | `b64a042` |
| 2026-08-11 | Xclipse 960 (Galaxy S26) | Chrome 151 | `_lite` | 720×1280 | 24,0 | 19,6 | 38,8 | 47,8 | `b64a042` |
| 2026-08-11 | Xclipse 960 (annoncé « 920, or similar ») | Firefox 153 | `_full` | 720×720 | 22,7 | 18,5 | 41,0 | 50,0 | `49b0c0e` |

**Cible de départ** : ≥ 25 fps, inférence < 50 ms/frame sur téléphone milieu de
gamme. **Cette cible est révisée plus bas, sur la base de ces mesures.**

### Ce qui est établi

- **Le delegate GPU sert bien.** Contexte GL puis `Graph successfully started
  running` sur les trois mesures : jamais de repli CPU silencieux.
- **Rien ne s'effondre sur 60 s.** p95 ≈ p50 + 20 % partout : pas de décrochage
  thermique, pas de pic GC.
- **L'inférence est le seul poste de coût.** 44 ms d'inférence pour 47 ms de
  budget de frame : 94 %. Le dessin, l'overlay et la FSM sont dans le bruit —
  optimiser le code applicatif ne rapporterait rien.
- **L'appareil est bien un S26.** Le Xclipse 960 est le GPU de sa génération.
  L'UA ne l'a pas dit (voir plus bas) ; la chaîne GPU, oui.

### La décision : on garde `_full`

Comparaison propre — même appareil, même navigateur, même résolution de capture,
seule la variante change :

| | `_full` | `_lite` | écart |
|---|---|---|---|
| fps p50 | 21,3 | 24,0 | +12,7 % |
| ms/frame p50 | 44,1 | 38,8 | −12,0 % |
| ms/frame p95 | 53,5 | 47,8 | −10,7 % |

**`_lite` gagne 12 % et rate quand même la cible de 25 fps.** Il n'ouvre donc
aucune porte : on paierait de la précision de pose pour un gain qui ne franchit
aucun seuil. `_full` reste le modèle par défaut. C'est la mesure qui tranche,
pas une préférence — et si un jour la cible descend sous 24 fps, la question se
rouvrira avec, cette fois, une mesure de précision en face (clips annotés, M2).

### La cible de 25 fps était arbitraire, et elle est fausse

Elle venait du cahier des charges comme objectif de départ, à réviser sur
données mesurées. Les données sont là : sur un **flagship 2026**, delegate GPU
actif, aucun goulot applicatif, BlazePose dans un navigateur plafonne à ~21 fps
en `full` et ~24 en `lite`. Un téléphone milieu de gamme fera moins.

Donc soit la cible est fausse, soit l'approche (BlazePose en WebGL) ne peut pas
la tenir. Rien dans ces mesures ne suggère un défaut d'implémentation à
corriger : le temps est dans le réseau de neurones.

**Cible révisée** : ≥ 20 fps p50 et p95 < 60 ms sur ce matériel, à re-mesurer sur
milieu de gamme avant d'être figée. Ce n'est pas un renoncement — c'est ce que
l'appareil fait réellement, et une cible qu'on ne mesure jamais atteinte ne sert
à rien.

**Conséquence à traiter, elle, en M2** : la fenêtre de dérivation vaut 100 ms
(`DIFFERENTIATION_WINDOW_MS`). À 21 fps, une frame dure 47 ms, donc la fenêtre
effective s'étire entre 100 et 148 ms — 50 % plus large que prévu. Elle lisse
d'autant les pics de vitesse angulaire, qui sont précisément le signal de
fatigue et de kipping. Les seuils `kip_tolerance_ms = 0,80 m/s` et le score
`tempo_control` ont été calés sur des fixtures synthétiques à 30 fps : ils
liront donc **bas** sur l'appareil. À recaler sur clips réels, pas à ajuster à
l'aveugle.

### Ce que ces mesures n'établissent pas

- **La comparaison entre navigateurs est faussée par la résolution.** Firefox a
  capturé 720×720 (518 k pixels), Chrome 720×1280 (921 k). Chrome a traité 78 %
  de pixels en plus pour 7 % de temps en plus — ce qui, au passage, montre que
  **le nombre de pixels d'entrée n'est pas le poste dominant** (MediaPipe
  redimensionne en interne). Baisser la résolution de capture n'est donc pas le
  levier qu'on pourrait croire.
- **Aucun appareil milieu de gamme n'a été mesuré**, et c'est le matériel que la
  cible vise.

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
