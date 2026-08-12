# Évaluation du comptage sur vidéo

Fait tourner le pipeline réel — MediaPipe, `FrameSampler`, `RepCounter` — sur des
clips dont on connaît le nombre vrai de répétitions.

```bash
cd web && npm run vendor-assets     # le modèle que l'app embarque
cd .. && PYTHONPATH=backend/src python -m vision.eval.evaluate \
    fixtures/clips/manifest.json --out docs/results/counting.json
```

Dépendances non incluses dans le backend (lourdes, et inutiles pour servir
l'API) :

```bash
pip install mediapipe opencv-python-headless
```

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
