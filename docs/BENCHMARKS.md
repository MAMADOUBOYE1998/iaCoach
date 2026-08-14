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

Trois clips du jeu sont annotés comme des tractions. La pose est parfaite sur
les trois (100 % des frames détectées), donc rien ne se joue à l'étage L1. Les
diagnostics `attempted` / `events` / `predicted` les séparent en **trois causes
distinctes**, dont une seule est un défaut de notre compteur.

| Clip | vrai | `attempted` | `events` | compté | flexion p1 | flexion p50 | flexion p95 |
|---|---|---|---|---|---|---|---|
| `082` | 9 | 14 | 3 | 3 | 0,023 | 0,135 | 0,463 |
| `083` | 20 | 0 | 0 | refus | — | — | — |
| `084` | 34 | 3 | 3 | 2 | **0,149** | 0,520 | 0,705 |

Rappel des seuils qu'on lit contre ces percentiles : `bottom_enter` 0,12 —
`bottom_exit` 0,20 — `rep_floor` 0,50 — `count_floor` 0,75.

### `084` — un défaut réel, et il est chez nous

**La flexion ne redescend jamais sous `bottom_enter`.** Le 1ᵉʳ percentile est à
0,149, au-dessus du seuil de 0,12. Seule une poignée de frames passe dessous, et
elles expliquent exactement les 3 armements observés sur 34 répétitions.

La FSM exige un retour confirmé en quasi-extension complète pour armer la rep
suivante. À 34,6 frames/rep (~1,15 s à 30 fps), l'athlète ne verrouille pas les
coudes entre les reps : le compteur s'arme une fois, compte, puis attend
indéfiniment une suspension bras tendus qui ne vient plus.

**Ce n'est pas un artefact de dataset.** Tout athlète enchaînant vite, ou en
kipping, sans verrouillage entre les reps sera compté à ~0 dans l'app. Et le
symptôme est « ne compte rien » — celui qu'on avait d'abord attribué à la
calibration.

Cause de fond : `bottom_enter` est une fraction de la plage calibrée, dont
l'extrémité en extension (`rom_max_deg`) est fixée par **la frame la plus tendue
du clip** — qui peut être un échauffement suspendu, pas la position réellement
tenue entre deux reps.

### `082` — la plage est définie par 7 frames

`attempted` = 14 pour 9 reps annotées : **la FSM voit bien le mouvement**, à peu
près au bon rythme. Mais la flexion p95 vaut 0,463, juste sous `rep_floor`
(0,50) : l'excursion typique plafonne vers 0,3-0,46 et seules 3 dépassent le
seuil.

Le minimum calibré (112,7°) est en dessous du 1ᵉʳ percentile des angles
(136,4°). **Moins de 1 % des frames — environ 7 — définit 40 % de la plage**, et
tous les seuils sont des fractions de cette plage. Sept frames affament les 780
autres.

C'est aussi pourquoi `--trim-percent 2` fait refuser ce clip : rogner la queue
en flexion ramène la plage à 27° et passe sous `MIN_SPAN_DEG`. **Le trim
symétrique est le mauvais outil ici** — il traite une flexion réelle mais brève
comme une aberration.

### Deux populations de frames, une incohérence

`rep_min_angle_deg` descend à **103,5°** sur `082`, sous le minimum calibré de
112,7°. Ce n'est pas une contradiction, c'est un défaut :

- la calibration n'utilise que les frames de confiance ≥ 0,70 (693 sur 791) ;
- le compteur consomme **toutes** les frames.

Les positions les plus fléchies sont donc les moins confiantes — auto-occlusion
en haut d'une traction, bras repliés, poignets près du visage. La calibration
rogne systématiquement l'extrémité en flexion de l'amplitude réelle, et
`normalised` sature ensuite à 1,0 avant que l'athlète n'atteigne son vrai
maximum.

### `083` — la répétition est réelle, l'amplitude ne l'est pas

Première lecture, à partir des seuls percentiles : la cadence annotée
(19,2 frames/rep, ≤ 0,64 s) est impossible pour une traction, donc l'annotation
compte autre chose. **La série temporelle a corrigé ça.**

Sur les 384 frames (29,0 fps mesurés, 13,21 s) :

| | |
|---|---|
| autocorrélation, meilleur pic | lag 18 frames = **621 ms**, r = 0,46 |
| soit | 1,61 Hz → **21,3 cycles** sur le clip (20 annotées) |
| deuxième pic | lag 35 = harmonique du même cycle, r = 0,46 |
| pic spectral | 1,66 Hz à **5,2×** le plancher de bruit |

La périodicité annotée **est présente dans l'angle de coude**, au bon rythme.
Ce n'est pas une annotation qui décrit autre chose.

Ce qui manque, c'est l'amplitude : **~5° crête-à-crête**, là où une traction en
parcourt ~110°. Et l'angle de coude ne quitte jamais la bande 119-155° : les
bras ne sont **jamais tendus**, à aucun instant des 13 secondes.

Deux lectures restent ouvertes, et elles appellent des correctifs opposés :

1. le mouvement n'est pas une traction (traversée de barres, balancement bras
   fléchis) — auquel cas le refus de calibrer est le bon comportement ;
2. l'étage pose écrase l'amplitude réelle.

### Et notre mesure de confiance ne peut pas les départager

`confidence` vaut **1,000 sur les 384 frames**. Notre confiance est la fraction
des landmarks moteurs dont la `visibility` MediaPipe dépasse 0,6 : c'est
l'affirmation qu'un landmark a été **trouvé**, pas qu'il a été trouvé au bon
endroit. Rien dans le pipeline ne mesurait la seconde chose.

C'est un angle mort dans une pièce porteuse : l'invariant « aucun landmark sous
le seuil de confiance n'est utilisé pour une correction » repose entièrement sur
ce score.

Ajouté en conséquence : `segment_cv`, le coefficient de variation de la longueur
métrique des segments rigides du bras (`worldLandmarks`). Un avant-bras ne
change pas de longueur ; si sa longueur mesurée varie de 20 % d'une frame à
l'autre, l'estimation 3D est mauvaise quoi qu'annonce `visibility` — et
contrairement à `visibility`, ça se vérifie sans vérité terrain.

Sur `083`, un `segment_cv` bas trancherait pour la lecture 1 (le suivi est bon,
le mouvement n'est pas une traction) ; un `segment_cv` haut pour la lecture 2.
**Non encore mesuré** — l'instrument est postérieur à la passe.

### Cadences annotées, pour situer

| Clip | frames/rep | durée d'une rep | plausible pour une traction ? |
|---|---|---|---|
| `082` | 87,9 | 2,93 s @30 fps | oui, tempo strict |
| `084` | 34,6 | 1,15 s @30 fps | rapide, plausible en kipping |
| `083` | 19,2 | **0,62 s mesuré** | pas à cette amplitude |

Seul `083` a sa cadence mesurée sur la série temporelle ; les deux autres sont
déduits de `frames / reps` en supposant 30 fps, et l'annotation pouvant ne
couvrir qu'un segment du clip, ce sont des **bornes hautes** de la période.

### Le signal contient les répétitions. C'est nous qui les jetons.

L'autocorrélation de l'angle de coude, sur les trois clips, aux maxima locaux
avec correction d'octave :

| Clip | vrai | FSM | autocorrélation | lag | r |
|---|---|---|---|---|---|
| `082` | 9 | 3 | **10,0** | 79 (2724 ms) | 0,379 |
| `083` | 20 | refus | **21,3** | 18 (621 ms) | 0,455 |
| `084` | 34 | 2 | **35,6** | 33 (1138 ms) | 0,710 |

| | MAE |
|---|---|
| `RepCounter` | **19,3** |
| rythme seul | **1,3** |

Les trois clips portent leur cadence annotée dans l'angle de coude, et sur `084`
elle est franche (r = 0,71, avec ses harmoniques à 66 et 100 frames). Le
problème n'est ni le footage, ni l'annotation, ni l'étage pose.

**`RepCounter` est verrouillé sur l'amplitude.** Tous ses seuils sont des
fractions d'une plage calibrée à partir des extrêmes ; un mouvement dont la
plage est mal estimée est invisible, si régulier soit-il. L'information de
répétition est dans la **périodicité**, et nous ne l'utilisons nulle part.

### Pourquoi ça ne remplace rien

Deux limites décisives, mesurées ou structurelles :

- **Aucune spécificité.** Sauter à la corde, ramer, touiller une casserole sont
  périodiques. `RepCounter` refuse 61 des 100 clips hors-domaine ; un compteur
  par périodicité les compterait tous les 100. Il n'est utilisable qu'**en aval
  d'un classifieur d'exercice**.
- **Aucune qualité par rep.** Un compte n'est pas un `RepEvent` : ni ROM, ni
  symétrie, ni tempo. Le contrat de coaching a besoin des trois, et ils
  *exigent* l'amplitude.

Les deux mesures convergent donc sur la même architecture : **M2 (classifieur)
puis comptage par périodicité, l'amplitude servant à la qualité et non au
déclenchement.** Ça déplace le repli RepNet de M4 vers le chemin principal.

Honnêteté sur ce chiffre : la règle de correction d'octave a été écrite **après**
avoir vu ces trois clips. Son MAE de 1,3 ici n'est pas une revendication de
généralisation — la ligne existe pour poser un plancher sous ce que le signal
contient, pas pour devenir le compteur.

### Suivi : `segment_cv`, et ce qu'il ne dit pas

| Clip | pire segment | confiance < 0,7 | conf. moitié fléchie / tendue | écart G-D fléchi / tendu |
|---|---|---|---|---|
| `082` | **12,6 %** | 98/791 | 0,886 / 0,992 | 10,4° / 6,0° |
| `083` | 8,6 % | 0/384 | 1,000 / 1,000 | 6,5° / 5,5° |
| `084` | 9,4 % | 0/1175 | 1,000 / 1,000 | 4,2° / 6,1° |

Un os ne change pas de longueur : 8 à 13 % de variation sur un avant-bras
mesuré, c'est ~2 cm de ballottement sur l'estimation 3D. **Aucun de ces clips
n'a un suivi propre**, et sur `083` et `084` la `visibility` MediaPipe n'en
signale rien — 0 frame sous le seuil de confiance.

Sur `082`, le suivi se dégrade **précisément pendant la traction** : confiance
0,886 en position fléchie contre 0,992 tendue, et l'écart gauche/droite double.
Le pire moment du suivi est le moment qui nous intéresse.

`083` a le meilleur `segment_cv` des trois et la plus petite amplitude, ce qui
penche pour « le mouvement n'est pas une traction » plutôt que « la pose écrase
l'amplitude ». Mais 8,6 % reste trop élevé pour trancher franchement, et je n'ai
pas regardé les vidéos. **Ça reste ouvert.**

### Ce que ce jeu peut et ne peut pas trancher

Notre compteur est conçu autour d'une **calibration volontaire par athlète**.
Sur du footage tiers, on la remplace par l'amplitude observée dans le clip — et
`082` montre le prix : la plage est prise en otage par quelques frames.

QUVA ne validera donc pas notre précision de comptage. Il a rendu mieux : le
défaut `084` (verrou `bottom_enter`), les deux populations de frames, l'angle
mort de la confiance, et surtout la démonstration que **le signal porte les reps
que nous jetons**.

**La mesure décisive reste une séance réelle**, calibration volontaire comprise,
enregistrée sur le téléphone à ses ~21 fps réels.

## Portillon de classification — spécificité mesurée

Les 100 clips QUVA, aucun n'étant un exercice suivi. Le compteur ne tourne que
si le classifieur nomme l'exercice de la séance.

| Date | Clips | Faux positifs | Reps inventées | Pire clip |
|---|---|---|---|---|
| 2026-08-13, sans portillon (`d89f668`) | 100 | 31 (**31 %**) | 114 | 14 |
| 2026-08-13, portillon traction (`40713fd`) | 100 | **1 (1 %)** | **5** | 5 |
| 2026-08-14, `hips_fold` (`5fdeacd`) | 100 | 1 (1 %) | 5 | 5 |
| 2026-08-14, `feet_planted` (`aaa215f`) | 97 + 3 hors dénominateur | 1 (1 %) | 5 | 5 |

Ce 1 % est à lire avec le rappel mesuré plus bas — **0/3 sur les vraies
tractions du jeu** — sans quoi il flatte un portillon qui refuse aussi les
positifs.

Le seul survivant est `040_monkey_bars`, classé `pull_up` sur 91,5 % des
fenêtres. C'est un échec loyal : quelqu'un suspendu à des barres de singe a les
mains au-dessus des épaules, le buste vertical et les coudes qui travaillent.
La géométrie *est* celle d'une traction.

### Ce que ce 1 % ne dit pas

Il vaut pour une séance de tractions. Le même fichier montre pourquoi :

| Étiquette rendue | Clips |
|---|---|
| `squat` | 34 |
| `unknown` | 33 |
| `dip` | 11 |
| `push_up` | 10 |
| (aucune pose détectée) | 7 |
| `pull_up` | 3 |
| `l_sit` | 2 |

**60 clips sur 100 reçoivent le nom d'un exercice réel**, 41 avec plus de la
moitié des fenêtres d'accord. Seuls 33 sont refusés. Le portillon tient pour la
traction parce que la traction a une signature géométrique unique — les mains
au-dessus des épaules — pas parce que le classifieur est bon.

Le portillon simulé pour chaque exercice le chiffre :

| Si la séance était | Clips laissés passer | Faux positifs | Reps inventées |
|---|---|---|---|
| `pull_up` | 3 | **1** | 5 |
| `push_up` | 10 | 3 | 9 |
| `dip` | 11 | 6 | 30 |
| `squat` | 34 | **16** | **55** |
| *(sans portillon)* | 100 | 31 | 114 |

Sur une séance de squats, le portillon ne retirait que la moitié du problème.

### La règle `squat` était creuse, et ma fixture le cachait

`min(genou travaille, bras immobiles, buste plutôt vertical)` se lit : « debout,
les jambes bougent, les bras non ». Ça décrit aussi marcher, pédaler et sauter à
la corde — d'où les 34 étiquettes.

Ce qui manquait est ce qui définit un squat : **la hanche fléchit**, d'environ
130°. Pédaler, marcher, sauter en fléchissent bien moins.

Et si aucun test ne l'avait attrapé, c'est que **ma pose de squat synthétique
gardait la hanche rigide** et ne bougeait que la cheville. Aucun squat ne fait
ça. La fixture était fausse avant la règle.

Corrigé : `hip_rom_deg` ajouté aux deux runtimes, terme `hips_fold` dans la
règle, et pose synthétique refaite — hanche 180°→82°, genou 173°→52° sur la
plage utilisée, soit un squat profond mais réel.

### La prédiction était fausse (passe du 2026-08-14)

Prédiction enregistrée : les 34 étiquettes `squat` tombent. Mesuré :

| | `squat` | Portillon squat simulé : clips / FP / reps |
|---|---|---|
| avant `hips_fold` (`40713fd`) | 34 | 34 / 16 / 55 |
| après `hips_fold` (`5fdeacd`) | **30** | **34 / 16 / 55** |

Quatre clips déplacés, et le portillon squat simulé **identique au clip près**.
Anatomiquement juste, pratiquement nul. Les quatre qui bougent (`033_hometrainer`,
`038`/`039_monkey_bars`, `083_pullups`) étaient déjà les plus faibles.

### Ce que la passe a réellement montré

Le classifieur étiquette `squat` **les deux vraies tractions du jeu** :

| Clip | Étiquette | Part des fenêtres | Amplitude coude p1–p99 |
|---|---|---|---|
| `082_pullups_monkey_bar` | `squat` | 95,3 % | 34,6° |
| `083_pullups_monkey_bar` | `unknown` | — | 29,4° |
| `084_pullups_monkey_bar` | `squat` | **99,8 %** | 40,0° |

Une traction parcourt environ 130° du coude. Ces clips en montrent 30 à 40 :
**l'étage de pose perd les bras**, donc `arms_still` est *satisfait*, et un
athlète qui kippe fournit le reste — buste vertical, genoux qui balancent.

Deux conséquences.

La première est une règle incomplète : rien ne disait que l'athlète a les pieds
au sol. Corrigé par `feet_planted` (`_at_most(wrist_above_shoulder, 0.0, 0.5)`),
avec une fixture `swinging_hang_not_a_squat` reconstruite depuis ces clips —
elle vaut 0,785 en `squat` sans le terme, 0,0 avec. Le squat en barre au-dessus
de la tête (*overhead squat*) échouerait ce terme ; il n'est pas au catalogue.

La seconde est plus importante : **`arms_still` et `feet_planted` ne sont pas la
même sorte de preuve**, bien que tous deux formulés négativement. Le premier est
satisfait par l'*absence* de signal, donc il se déclenche d'autant plus fort que
le suivi échoue. Le second est un fait positif sur la position du corps. Toute
règle du premier type est un faux positif en attente d'une mauvaise vidéo.

### Le « 1 % » était en partie acheté avec le rappel

Le jeu QUVA contient trois vraies tractions. Le portillon traction n'en a
reconnu **aucune** — et c'est ce qui faisait baisser le taux de faux positifs.
Un portillon qui refuse tout obtient 0 %.

Corrigé dans le harnais : les clips vraiment dans le domaine sont marqués
`in_domain` par l'importeur, sortis du dénominateur de spécificité, et
`gate_recall` est publié à côté. **Rappel du portillon traction sur QUVA : 0/3.**
La spécificité seule est trivialement gagnable et ne veut rien dire isolée.

### Vérification `feet_planted` (passe du 2026-08-14, `spec4`)

Prédiction : `082` et `084` quittent `squat`. **Une sur deux.**

| Clip | avant | après |
|---|---|---|
| `082_pullups` | `squat` 95,3 % | `unknown` |
| `083_pullups` | `unknown` | `unknown` |
| `084_pullups` | `squat` 99,8 % | **`squat` 99,8 %** — inchangé |

Étiquettes `squat` : 30 → 28. Portillon squat simulé : 34/16/55 → 27/14/50.

`084` est le résultat intéressant. Pour qu'une fenêtre score `squat` malgré
`feet_planted`, il faut `wrist_above_shoulder ≲ 0,2` : **MediaPipe ne place pas
les mains au-dessus des épaules sur un athlète suspendu à une barre.** Ce n'est
plus « l'amplitude du coude est sous-estimée », c'est la posture entière qui
n'est pas reconnue. Sauf si le cadrage n'est pas celui qu'on suppose — et ces
deux causes appellent des correctifs opposés.

Impossible de trancher depuis ce fichier : les features de fenêtre étaient
calculées puis jetées. `--dump-angles` écrit désormais aussi
`<clip>_windows.csv` (étiquette, motif, features, score par exercice), ce qui
rend la question mesurable au lieu d'argumentable. C'est le prochain pas, avant
tout nouveau seuil.

Attention à la lecture du tableau principal : les faux positifs passent de 31/100
à 29/97 **sans qu'aucun clip ne change**. Les trois tractions sortent du
dénominateur, et deux d'entre elles y comptaient comme faux positifs. Ce n'est
pas un progrès, c'est une comptabilité corrigée.

`gate_recall` reste **0/3**.

La sensibilité reste hors de portée de ce jeu — trois tractions dégradées, aucun
squat, aucun dip, aucune pompe. Seule une séance filmée par l'athlète peut la
mesurer.

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
