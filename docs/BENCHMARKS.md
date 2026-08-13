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

## Spécificité — footage qui n'est pas l'exercice

QUVA Repetition, 100 clips de mouvements répétitifs quelconques (corde à sauter,
aviron, coiffage, pelletage). Question posée : **le compteur invente-t-il des
tractions quand l'athlète n'en fait pas ?**

| Date | Jeu | Clips | Refus de calibrer | Évalués | Clips à faux positif | Taux | Reps inventées | Pire clip |
|---|---|---|---|---|---|---|---|---|
| 2026-08-11 | QUVA (`d89f668`) | 100 | 61 | 39 | 31 | **31 %** | 114 | 14 |

**31 %, c'est mauvais**, et la cause est structurelle, pas un réglage à corriger :
la FSM compte des cycles de flexion de coude. L'aviron *est* un cycle de flexion
de coude. Le brossage de cheveux aussi. Les pires faux positifs le disent
clairement — `055_cable_chop` 14 reps, `034_rowing_machine` 10 (pour 9 coups
d'aviron réels : le compteur a compté juste, mais pas ce qu'on lui demandait),
`080_brushing_hair` 9.

Aucun seuil ne sépare ces mouvements d'une traction, parce que **rien dans le
pipeline ne regarde de quel exercice il s'agit**. C'est le classifieur de M2, et
ce chiffre en est la justification chiffrée plutôt qu'une intuition.

Deux pistes mesurées sur ces données, à traiter avant le classifieur :

- **11 des 31 clips fautifs** portent `low_confidence` sur au moins autant de
  reps qu'ils en comptent — 54 des 114 reps inventées. Aujourd'hui une rep dont
  la confiance moyenne est sous 0,70 est **comptée quand même** (seul le retour
  correctif est supprimé). Ne pas la compter supprimerait près de la moitié des
  faux positifs, au prix de reps perdues quand le suivi décroche sur une vraie
  séance. Arbitrage à mesurer, pas à trancher au jugé.
- La détection de pose n'est **pas** le maillon faible : médiane de 97 % des
  frames avec une pose exploitable, et seulement 9 clips sous 20 %.

## Sensibilité — les tractions présentes dans QUVA

Trois clips du jeu sont de vraies tractions. Le résultat est plus préoccupant
que les faux positifs :

| Clip | Reps réelles | Comptées | Frames avec pose |
|---|---|---|---|
| `082_pullups_monkey_bar` | 9 | **3** | 791/791 |
| `083_pullups_monkey_bar` | 20 | **refus de calibrer** | 384/384 |
| `084_pullups_monkey_bar` | 34 | **2** | 1175/1175 |

La pose est parfaite sur les trois (100 % des frames), donc le problème est
entièrement dans le comptage.

### Ce que la mesure a tranché — et ce qu'elle a invalidé

Trois causes étaient possibles : la FSM ne voit pas les cycles ; elle les voit
et refuse de les compter (`count_floor`) ; ou la calibration `min`/`max` est
gonflée par une frame aberrante — et comme tous les seuils sont des fractions de
la plage, une plage gonflée affame toutes les reps d'un coup.

| Clip | `events` | comptées | plage brute | plage à 2-98 % |
|---|---|---|---|---|
| `082` | 3 | 3 | 112,7-171,8° (59,1°) | **< 40° → refus** |
| `083` | — | refus | **< 40° → refus** | < 40° → refus |
| `084` | 3 | 2 | 117,2-172,1° (54,9°) | **< 40° → refus** |

- **`count_floor` est hors de cause.** `events` ≈ `predicted` : la FSM n'émet
  que 3 cycles, elle n'en refuse pas 6 ou 31.
- **`--trim-percent 2` fait refuser les trois clips.** Écarter 2 % de chaque
  queue retire ≥19° sur `082`. Le signal est donc quasi plat, avec de brèves
  excursions — ou porteur d'une aberration franche à une extrémité.

Ce qui reste indéterminé, et pourquoi : **quelle** queue porte ces 19°. Une
flexion réelle mais brève et une hyperextension aberrante élargissent toutes
deux l'écart `min`/`max`, et appellent des correctifs opposés.

### L'instrument était en cause aussi

`peak_angles_deg` a été retiré : il rapportait `max(angle)` sur la rep, c'est-à-
dire le point le plus **tendu**. Une rep se fermant par construction au retour
en extension, ces 166-172° étaient tautologiques. Le diagnostic construit pour
départager la troisième hypothèse ne la mesurait pas.

Remplacé par : `attempted` (toute excursion vue, même sous `rep_floor`, donc
invisible jusqu'ici), `angle_percentiles` (p1…p99 du signal brut — dit **quelle**
queue porte la plage, y compris quand la calibration refuse), `flexion_percentiles`
(le signal normalisé que la FSM consomme, lisible directement contre
`bottom_exit` 0,20 / `rep_floor` 0,50 / `count_floor` 0,75), `rep_rom` et
`rep_min_angle_deg`. Plus `--dump-angles`, qui écrit la série temporelle : les
percentiles disent qu'une distribution est étroite, seule la série dit si c'est
un signal plat ou un cycle propre au mauvais décalage.

`attempted` ≥ `events` ≥ `predicted` s'emboîtent, et l'étape où le nombre
s'effondre nomme le responsable.

**Mesure à refaire** avec ces diagnostics. Tant qu'elle n'existe pas, la
précision de comptage reste non mesurée — ces lignes disent qu'il y a un
problème et éliminent une hypothèse sur trois, pas laquelle des deux restantes.

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
