# Évaluation du comptage sur vidéo

Fait tourner le pipeline réel — MediaPipe, `FrameSampler`, `RepCounter` — sur des
clips dont on connaît le nombre vrai de répétitions.

### Installation

Depuis la racine du dépôt. Un venv, parce que le python système de macOS refuse
les installations directes (PEP 668) :

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e "./backend[eval]"        # iacoach + mediapipe + opencv

mkdir -p web/public/models
curl -L -o web/public/models/pose_landmarker_full.task \
  https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_full/float16/1/pose_landmarker_full.task
```

Le `curl` remplace `npm run vendor-assets` : c'est le même fichier, et il n'y a
aucune raison d'installer une chaîne JavaScript pour évaluer des vidéos.

Si pip ne trouve pas de wheel `mediapipe`, la version de Python est trop
récente — utiliser 3.12.

### Lancer

```bash
python -m vision.eval.evaluate fixtures/clips/manifest.json --out counting.json
```

`PYTHONPATH` devient inutile une fois `backend` installé en editable.

Les chemins d'un manifeste sont résolus **depuis le manifeste lui-même**, ce qui
casse dès que le manifeste vit dans le dépôt et les vidéos ailleurs.
`--clips-root` pointe le dossier des vidéos :

```bash
python -m vision.eval.evaluate vision/eval/manifest.pullups.json \
    --clips-root ~/Downloads/QUVARepetitionDataset/videos --out brut.json
```

Si **aucun** clip n'est trouvé, la commande sort en erreur au lieu de rendre un
résumé vide : un résumé vide ressemble à une mesure.

Et si un clip n'est pas là où le manifeste le déclare, il est **cherché par nom
sous la racine** avant d'être déclaré absent — c'est exactement ce qu'on
s'apprêtait à faire à la main. La déviation est signalée (`dévié`) et inscrite
dans le `note` du clip : une passe qui a mesuré d'autres fichiers que ceux
nommés doit rester reconstituable. Deux fichiers du même nom sous la racine ne
sont pas « trouvés » mais `nom ambigu` : deviner entre eux scorerait une vidéo
contre l'annotation de l'autre.

## Quel corps est mesuré

MediaPipe rend des poses, pas des identités. Avec `num_poses=1` il rend celle
qu'il a préférée sur *cette* frame, et rien en aval ne peut voir qu'une autre
personne a répondu. C'est le défaut mesuré sur `084` : 1175 frames d'un corps
droit, suivi avec une confiance de 1,0, dont les mains ne montent jamais
au-dessus des épaules, sur un clip annoté « tractions ». Aucun seuil
biomécanique n'était en cause — c'était le mauvais corps.

`SubjectTracker` choisit une fois puis suit. **La sélection tourne sur les
landmarks normalisés, jamais sur les `worldLandmarks`** : ces derniers sont
recentrés sur les hanches de *chaque* sujet, donc tout le monde est à l'origine
et le seul signal qui distingue deux personnes a disparu. C'est le seul endroit
du dépôt où le jeu 2D est la bonne entrée, et il l'est précisément parce qu'il
dépend du cadrage.

Ce que ça corrige et ce que ça ne corrige pas :

- **Le basculement**, oui. Une fois un corps choisi, on le suit au lieu de
  redécider à chaque frame.
- **L'acquisition**, non. Si la première frame donne la mauvaise personne, la
  continuité verrouille l'erreur et la rend plus stable. Le coût est réel.

D'où l'instrumentation, reportée par clip dans `subject` :

| champ | ce qu'il dit |
|---|---|
| `max_candidates` | **1 ⇒ la sélection n'a jamais eu le choix.** Un mauvais sujet sur un tel clip est un échec de *détection*, aucune politique n'y pouvait rien. |
| `frames_with_choice` | frames où plusieurs corps étaient offerts |
| `acquisitions` | > 1 ⇒ la piste a été perdue et reprise, la seconde peut être quelqu'un d'autre |
| `dropped_frames` | frames où un corps existait mais aucun ne collait à la piste |

**Mesuré, et désactivé par défaut.** `--max-poses 3` coûte 26 % de débit
(54,9 → 40,6 fps sur 48 030 frames) et n'améliore aucune métrique de comptage :
faux positifs 29 → 28, reps inventées 109 → 109. Détail dans
[`docs/BENCHMARKS.md`](../../docs/BENCHMARKS.md). Le code reste parce que le cas
multi-personnes est réel ; ce jeu n'en contient simplement pas la preuve.

`--max-poses 1` (défaut) **court-circuite le tracker entièrement**. Il le
traversait au début, ce qui rendait la comparaison illisible : sans rien à
choisir, il abandonnait quand même les frames dont l'unique corps avait
« téléporté », changeant le comptage sur 11 clips sur 97. La continuité comme
filtre de qualité est une autre fonctionnalité que la sélection de sujet.

Attention quand même : **`num_poses` change la sortie du détecteur lui-même.**
Sur `084`, mêmes 1175 frames détectées et `predicted` qui passe de 2 à 8. Aucun
drapeau ne peut isoler proprement la sélection — c'est une propriété de
MediaPipe.

### Quand le sujet n'est même pas candidat

Si `subject.max_candidates` vaut 1, la sélection n'a rien pu faire : l'athlète
n'a pas été mal choisi, il n'a pas été proposé. Le bloc `detection` répond alors
à la question suivante.

| champ | ce qu'il dit |
|---|---|
| `box_height` | part de l'image occupée par le corps suivi. Le détecteur a une taille minimale pratique ; un athlète filmé large peut passer dessous quand un passant plus proche ne passe pas. |
| `box_centre_y_excursion` | déplacement vertical du corps suivi (p90 − p10). **Une traction translate tout le corps d'environ un demi-torse à chaque répétition.** Une boîte immobile sur 34 répétitions annotées n'appartient pas à la personne qui les fait. |
| `limb_ratio` / `limb_ratio_implausible` | humérus sur avant-bras dans `worldLandmarks`. Tout humain est entre 1,05 et 1,35, enfants compris. En dessous, ce n'est pas une morphologie inhabituelle, c'est un squelette mal ajusté. Calculé **par bras**, et seulement quand épaule, coude et poignet passent tous les trois `VISIBILITY_THRESHOLD` — invariant n°5. |
| `limb_ratio_frames` | part du clip sur laquelle le rapport a pu être mesuré. Sans elle, un clip mesuré sur 5 % de ses frames se lit comme un clip mesuré sur toutes. |
| `limb_ratio_cv` | variation de ce rapport sur le clip. Les deux os sont **rigides** : leur rapport est une constante de l'athlète, que ni la posture, ni la distance, ni l'angle de caméra ne déplacent, et l'échelle attribuée par MediaPipe à chaque détection s'annule. **Zéro est la seule valeur correcte, pour n'importe quel clip.** Toute variation est une erreur d'estimation sans explication concurrente. |
| `limb_ratio_2d` | le même rapport en espace image, **conservé comme contexte et volontairement non noté**. La bande 1,05–1,35 est un fait d'anatomie 3D ; la projection raccourcit le membre pointé vers la caméra, donc un squelette correct en sort en espace image tout le temps. Mesuré sur QUVA, la 2D est hors bande sur *plus* de frames que la 3D (76 % contre 64 %) — c'est l'artefact de projection, pas un résultat. |

Les deux premiers sont complémentaires et aucun ne remplace l'autre. La bande
existe parce que `segment_cv` a été sur-interprété une fois : la stabilité d'une
longueur dit que l'ajustement est **constant**, pas qu'il est **juste** — un
squelette constamment faux est parfaitement stable, et seule la bande le voit.
La variation prend l'inverse : un rapport qui oscille à l'intérieur de la bande
est invisible à la bande. Et elle est la plus solide des deux, parce qu'elle
n'exige pas que `HUMAN_LIMB_RATIO` soit la bonne bande : une bande lue sur de
l'anthropométrie se discute, un os rigide non.

Et `--running-mode image` teste la cause structurelle : en mode `video`,
MediaPipe réutilise la région d'intérêt de la frame précédente et ne relance le
détecteur complet que lorsqu'il perd le suivi — donc un second corps entrant
dans la scène peut n'être **jamais cherché**. Le mode `image` redétecte chaque
frame. Si `max_candidates` monte, c'est la réutilisation de la ROI qui cachait
l'athlète ; sinon il n'est pas détectable du tout.

```bash
python -m vision.eval.evaluate quva.json --out-of-domain \
    --running-mode image --max-poses 3 --out detection.json
```

## Diagnostiquer un comptage faux

Un compteur qui rend 3 au lieu de 9 a trois explications incompatibles, et le
nombre final n'en désigne aucune. Trois compteurs emboîtés le font :

| | ce qu'il compte |
|---|---|
| `attempted` | toute excursion partie du bas et revenue, si superficielle soit-elle |
| `events` | celles assez profondes pour émettre un `RepEvent` (≥ `rep_floor`) |
| `predicted` | celles assez profondes pour compter (≥ `count_floor`) |

L'étape où le nombre s'effondre nomme le responsable. `attempted` ≪ vérité : la
FSM ne voit rien, le signal ou la plage sont en cause. `events` ≪ `attempted` :
les cycles existent mais sont trop peu amples relativement à la plage calibrée.
`predicted` ≪ `events` : c'est `count_floor`.

`angle_percentiles` (signal brut) et `flexion_percentiles` (signal normalisé que
la FSM consomme, lisible contre `bottom_exit` 0,20 / `rep_floor` 0,50 /
`count_floor` 0,75) disent **quelle** queue de distribution porte l'amplitude —
une flexion réelle brève et une aberration en hyperextension élargissent
identiquement l'écart `min`/`max` et appellent des correctifs opposés. Les
percentiles sont renseignés **même quand la calibration refuse**, cas où ils sont
la seule preuve disponible.

Et quand les percentiles ne suffisent pas, `--dump-angles` écrit la série
temporelle par clip :

```bash
python -m vision.eval.evaluate vision/eval/manifest.pullups.json \
    --clips-root ~/Downloads/QUVARepetitionDataset/videos \
    --dump-angles angles/ --out brut.json
```

Deux `.csv` par clip.

`<clip>.csv` — une ligne par frame : `t_ms`, angles gauche/droit/moyen,
confiance, puis la longueur des quatre segments rigides du bras. Les percentiles
disent qu'une distribution est étroite ; seule la série dit si c'est un signal
plat, un signal rapide sous-échantillonné, ou un cycle propre au mauvais
décalage.

Les longueurs de segments sont là parce que `confidence` dérive de la
`visibility` de MediaPipe, qui affirme qu'un landmark a été **trouvé**, pas
qu'il a été trouvé au bon endroit. Un os ne change pas de longueur : ce qui
varie dans ces colonnes est l'estimation 3D qui bouge, et ça ne s'interprète
qu'à côté de l'angle mesuré sur la même frame.

S'y ajoutent trois relations verticales **signées** :
`shoulder_above_hip`, `knee_below_hip`, `wrist_above_shoulder_y` — rapportées
aussi par clip dans le JSON (`orientation`), médiane et fraction de frames du
mauvais côté de zéro.

Tout le reste de l'étage d'analyse est constitué d'angles — invariants par
rotation — et `trunk_verticality` prend une valeur absolue. **Un athlète suivi à
l'envers y est donc indiscernable d'un athlète debout.** `shoulder_above_hip` est
le seul signe qui ne ment pas : debout, suspendu, en squat, en pleine muscle-up,
un corps humain a toujours les épaules au-dessus des hanches. Négatif, le
squelette est retourné et tous les angles en aval sont lus sur un corps à
l'envers.

`<clip>_windows.csv` — une ligne par fenêtre de classification : l'étiquette,
sa confiance, le motif, les features de la fenêtre (`wrist_above_shoulder`,
`trunk_verticality`, amplitudes coude/genou/hanche…) et le score de chaque
exercice.

Sans ce fichier, une étiquette fausse est indiscutable. `084` est appelé `squat`
sur 99,8 % de ses fenêtres pendant que l'athlète fait des tractions, et il a
fallu ces colonnes pour établir que ni la règle ni aucun seuil n'était en cause :
les mains ne passent au-dessus des épaules sur **aucune** des 1175 frames, alors
que les épaules restent au-dessus des hanches sur toutes. Corps droit, mains
jamais en haut — `num_poses=1` suit quelqu'un d'autre.

Une fenêtre refusée avant d'avoir des features laisse les colonnes **vides**,
jamais à zéro : `wrist_above_shoulder` vaut légitimement 0 quand les mains sont
à hauteur d'épaule, et un zéro fabriquerait la preuve que ce fichier existe pour
fournir.

## Ce que les chiffres veulent dire

`MAE`, `OBO` (à ±1 répétition près) et `MAPE` : les métriques de la littérature
sur le comptage de répétitions, pour que nos résultats soient comparables aux
résultats publiés.

Le pipeline est mesuré **de bout en bout, pose comprise**. Compter parfaitement
à partir de keypoints parfaits ne dirait rien de ce que produit une caméra.

## Deux choses à ne pas oublier en lisant un résultat

**La calibration est estimée depuis le clip lui-même.** Dans l'app, l'athlète
calibre volontairement avant sa série ; ici on prend l'amplitude observée dans la
vidéo. C'est le seul choix possible sur du footage tiers, et il **flatte le
résultat** : on donne au compteur exactement la plage sur laquelle on va le
tester. Un score obtenu ainsi est une borne basse du travail restant.

**Un clip non évaluable n'est pas un échec à zéro.** Si l'amplitude ou le suivi
ne permettent pas de calibrer, le clip est compté dans `skipped` et sorti des
métriques. Un harnais qui note ses propres échecs comme des réussites annonce
des progrès qu'il n'a pas faits.

Détail des sources de données utilisables et de leurs limites :
[`docs/DATASETS.md`](../../docs/DATASETS.md).

## Importer un dataset téléchargé

```bash
python -m vision.eval.import_quva /chemin/vers/QUVARepetitionDataset \
    --out fixtures/clips/manifest.json
```

Le script **inspecte avant de conclure** : il affiche ce qu'il a réellement
trouvé — extensions, appariement vidéo/annotation, forme et premières valeurs
d'une annotation — avant d'écrire quoi que ce soit. Le format d'annotation de
QUVA n'est documenté nulle part d'accessible ; deviner produirait un manifeste
plausible et faux d'une répétition sur chaque ligne.

Vérifier **une** vidéo à la main avant de s'y fier. Si le compte est décalé de
1, relancer avec `--count-convention boundaries`.

### QUVA : une mesure de spécificité, pas de précision

C'est un jeu de mouvements **génériques** : corde à sauter, trampoline,
balançoire, touillage, coiffage. Aucune traction. Étiqueter ces clips `pull_up`
et mesurer une « précision » n'aurait aucun sens.

En revanche ils répondent à la question qui est *sous* la précision :

```bash
python -m vision.eval.evaluate fixtures/clips/manifest.json --out-of-domain
```

**Le compteur invente-t-il des répétitions quand l'athlète ne fait pas
l'exercice ?** C'est ce qui décide si un journal de séance est croyable. Un
compteur qui s'incrémente pendant une corde à sauter s'incrémentera aussi
pendant que tu ajustes ta prise, que tu restes suspendu, ou que quelqu'un passe
devant la caméra.

En mode `--out-of-domain`, refuser de calibrer est compté comme **correct** :
sur du footage qui n'est pas l'exercice, refuser est la bonne réponse. Le
chiffre qui compte est `false_positive_rate`.
