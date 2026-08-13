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
