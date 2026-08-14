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
`shoulder_above_hip`, `knee_below_hip`, `wrist_above_shoulder_y`.

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
sur 99,8 % de ses fenêtres pendant que l'athlète fait des tractions ; la règle
`squat` exige que les mains ne soient pas au-dessus des épaules, donc **soit**
MediaPipe ne les y place pas sur un athlète suspendu, **soit** le cadrage n'est
pas celui qu'on suppose. Ces deux causes appellent des correctifs opposés et
l'étiquette seule ne les sépare pas. Une fenêtre refusée avant d'avoir des
features laisse les colonnes **vides**, jamais à zéro — `wrist_above_shoulder`
vaut légitimement 0 quand les mains sont à hauteur d'épaule.

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
