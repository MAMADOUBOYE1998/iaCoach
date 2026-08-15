# Protocole — première séance filmée

Cette séance est la mesure que le projet attend depuis le début. Tout ce qui a
été mesuré jusqu'ici vient de QUVA, un jeu de mouvements génériques qui contient
**trois tractions dégradées, aucun squat, aucun dip, aucune pompe**. La
sensibilité — est-ce que ça compte les répétitions réelles — n'a donc jamais été
mesurée. Pas une fois.

Deux règles avant tout le reste.

**La vidéo ne quitte pas l'appareil.** Les clips restent sur le téléphone puis
sur votre machine. Rien n'est versionné, rien n'est envoyé. Les manifestes
contiennent des chemins absolus vers votre dossier personnel : ils restent hors
du dépôt eux aussi.

**La vérité terrain s'écrit pendant le tournage, pas après.** Trente clips se
ressemblent tous. Décider une semaine plus tard combien de répétitions contenait
le clip 17, et si le kip était volontaire, veut dire tout revisionner et deviner.
Le nom du fichier porte le compte ; c'est tout le protocole.

---

## Ce que chaque bloc débloque

| Bloc | Question ouverte | Ce qu'elle décide |
|---|---|---|
| 0 | Le biais `limb_ratio` survit-il sur **votre** caméra ? | **M4, go / no-go** |
| 1 | Une calibration délibérée change-t-elle les chiffres ? | À quel point QUVA était flatteur |
| 2 | Est-ce que ça compte les vraies répétitions ? | Tout |
| 2 | `gate_recall` = 0/3 : le portillon laisse-t-il passer une vraie traction ? | Si le portillon est livrable |
| 3 | Les règles `squat` / `dip` / `push_up` tiennent-elles ? | Elles n'ont jamais vu un vrai squat |
| 4 | Combien de répétitions inventées pendant le repos ? | Si l'app peut rester allumée entre les séries |
| 5 | fps réel sur l'appareil | Tous les seuils temporels |

---

## Nommage des fichiers

Cinq champs, séparés par `_` :

```
<ordre>_<exercice>_<variante>_<angle>_<reps>.mp4

01_idle_tpose_face_00.mp4        T-pose tenue immobile, 0 répétition
03_pullup_strict_face_05.mp4     5 tractions strictes, filmées de face
07_pullup_kip_face_05.mp4        5 tractions en kip volontaire
12_rest_deadhang_face_00.mp4     30 s suspendu immobile, 0 répétition
```

Exercices : `pullup`, `chinup`, `dip`, `pushup`, `squat`, `muscleup`, plus
`rest` et `idle` pour les clips sans exercice.

**La variante est le champ qui rend un seuil ajustable.** `kip_tolerance_ms` ne
peut pas être recalibré à partir de tractions strictes seules : rien dans le lot
ne se trouve de l'autre côté du seuil. Il faut des fautes **décidées à l'avance**
— l'étiquette est le plan, pas une annotation faite après coup.

Un nom illisible est refusé plutôt que deviné. Un compte inventé par défaut
entrerait dans un benchmark comme si vous l'aviez annoncé.

---

## Cadrage — identique pour tous les clips d'un même angle

- **Téléphone fixe.** Trépied, ou calé contre un sac. Pas de main qui tient.
- **Le corps remplit la hauteur du cadre**, marge comprise en haut et en bas :
  une traction déplace tout le corps d'environ un demi-torse. Sur QUVA, les
  clips de tractions donnaient `box_height` entre 0,68 et 0,83 — visez au moins
  ça.
- **Filmez à 30 fps si le téléphone le propose.** Le harnais sait rejouer un
  clip plus lentement (`--target-fps`), jamais plus vite : partir de 30 marche,
  partir de 60 marche aussi, mais 30 est le point de comparaison direct avec les
  chiffres existants.
- **Les trois angles** : `face` (perpendiculaire au plan du corps), `troisquart`
  (~45°), `profil`. Le même exercice, filmé trois fois, dit si le défaut de
  landmarks dépend du point de vue — ce qu'on ne peut pas savoir autrement.
- **Bras nus si possible.** Le contraste au coude est un facteur plausible de
  qualité d'ajustement, et un clip `idle` en manches longues coûte 30 s à tester.

**Annoncez le compte à voix haute pendant la série.** C'est la sauvegarde du nom
de fichier.

---

## Bloc 0 — la référence (5 min, aucune fatigue)

**C'est le bloc le plus important de la soirée, et le moins fatigant. Ne le
sautez pas, même si le reste tombe à l'eau.**

| Clip | Durée | Ce qu'il mesure |
|---|---|---|
| `01_idle_tpose_face_00.mp4` | 15 s | T-pose : bras à l'horizontale, tendus, immobiles |
| `02_idle_still_face_00.mp4` | 20 s | Debout, bras le long du corps, immobile |
| `03_idle_still_profil_00.mp4` | 20 s | Idem, de profil |

La T-pose est le test décisif. Les deux bras sont **dans le plan de l'image** :
aucun raccourci de perspective, aucune ambiguïté de profondeur, aucune
occlusion, aucun mouvement. Si le rapport humérus/avant-bras est anatomiquement
impossible **là**, il n'existe plus aucune excuse — ce n'est ni le cadrage, ni la
vitesse, ni la visibilité. C'est le modèle, et M4 devient obligatoire.

Sur QUVA, 69 clips sur 96 ont un squelette impossible sur plus de la moitié de
leurs frames, et sur les trois clips de tractions MediaPipe déclare une
visibilité supérieure à 0,6 sur 100 % des frames pendant que le rapport est
impossible sur 96 % d'entre elles. **Le signal de confiance du modèle est aveugle
à ce défaut.** La T-pose dit si ça vient de MediaPipe ou de QUVA.

---

## Bloc 1 — calibration délibérée (3 min)

`04_pullup_calib_face_03.mp4` — **3 tractions lentes, amplitude maximale**, bras
complètement tendus en bas, menton franchement au-dessus de la barre.

Le harnais estime aujourd'hui la calibration depuis le clip lui-même : il donne
au compteur l'amplitude exacte sur laquelle il va être testé, ce qui **flatte le
résultat**. L'app, elle, calibre délibérément. Ce clip est le premier à
reproduire ce que l'app fait vraiment, et l'écart entre les deux est la mesure de
combien les chiffres QUVA étaient optimistes.

---

## Bloc 2 — tractions (30 répétitions, le cœur de la mesure)

Séries de 5, repos complet entre chaque. Annoncez la variante avant de commencer.

| Clip | Variante | Consigne |
|---|---|---|
| `05_pullup_strict_face_05.mp4` | stricte | Amplitude pleine, tronc immobile, tempo naturel |
| `06_pullup_strict_troisquart_05.mp4` | stricte | Identique, caméra à 45° |
| `07_pullup_strict_profil_05.mp4` | stricte | Identique, caméra de profil |
| `08_pullup_kip_face_05.mp4` | kip | **Kip volontaire et franc** : jambes et hanches |
| `09_pullup_demi_face_05.mp4` | demi | **Arrêt volontaire à 90° de coude**, jamais en haut |
| `10_pullup_lent_face_05.mp4` | lent | 3 s de montée, 3 s de descente |

Les trois premières donnent la sensibilité et `gate_recall`. Les trois dernières
donnent les seuils : `kip` contre `strict` recalibre `kip_tolerance_ms` (0,80 m/s
aujourd'hui, valeur posée jamais mesurée) et `trunk_tolerance_deg` (30°) ; `demi`
contre `strict` recalibre le seuil de ROM ; `lent` teste le tempo et l'entrée en
position basse — c'est là que le verrou `bottom_enter` diagnostiqué sur `084`
devrait se manifester ou non.

**Si la fatigue coupe court**, la priorité est : `05` d'abord (la première vraie
traction jamais mesurée), puis `08`, puis le reste. Trois angles d'une série
stricte valent mieux que six variantes bâclées.

---

## Bloc 3 — les exercices jamais vus (10 min, peu fatigant)

Les règles `squat`, `dip` et `push_up` du classifieur ont été écrites et
mesurées contre **rien**. `feet_planted` et `hips_fold` ont été ajoutées et
validées sur des fixtures synthétiques et sur des clips QUVA qui n'étaient pas
des squats.

| Clip | |
|---|---|
| `11_squat_strict_face_08.mp4` | 8 squats, amplitude complète |
| `12_squat_strict_profil_08.mp4` | idem, de profil |
| `13_pushup_strict_profil_08.mp4` | 8 pompes, de profil (le meilleur angle) |
| `14_dip_strict_face_06.mp4` | 6 dips |

---

## Bloc 4 — les négatifs (5 min)

Ce que l'app verra si elle reste allumée entre les séries. C'est la spécificité
sur **votre** matériel, dans les moments qui comptent.

| Clip | Durée | Pourquoi celui-là |
|---|---|---|
| `15_rest_deadhang_face_00.mp4` | 30 s | **Suspendu immobile, sans tirer.** Le négatif le plus dur : une position basse permanente, exactement ce que le compteur pourrait lire comme une répétition en cours |
| `16_rest_marche_face_00.mp4` | 30 s | Marcher dans le cadre, s'éloigner, revenir |
| `17_rest_reglage_face_00.mp4` | 30 s | Ajuster le téléphone, boire, se magnésier |
| `18_rest_assis_face_00.mp4` | 30 s | Assis, immobile |

Sur QUVA, 29 clips sur 97 produisaient au moins une répétition inventée, 109 au
total. Mais QUVA filme du jardinage et de la natation — pas votre barre, pendant
votre repos.

---

## Bloc 5 — la séance live dans la PWA (5 min)

Une série de 5 tractions **comptée par l'app sur le téléphone**, via
https://mamadouboye1998.github.io/iaCoach/ (voir `PHONE_TESTING.md`).

Notez : le **fps affiché**, le compte de l'app, votre compte réel. C'est la seule
source pour le débit réel de l'appareil, et le seul moment où la calibration
délibérée, la boucle temps réel et l'UX sont testées ensemble. Ce clip n'est pas
rejouable — d'où le bloc 2, qui l'est.

---

## Après la séance

```bash
# 1. Manifestes depuis les noms de fichiers. Vérifiez le récapitulatif imprimé
#    avant tout le reste : il dit ce qui a réellement été compris.
python -m vision.eval.import_session ~/seances/2026-08-15

# 2. Sensibilité — MAE, OBO, MAPE contre le compte annoncé. Jamais mesurée.
python -m vision.eval.evaluate ~/seances/2026-08-15/session.json --out sens.json

# 3. Spécificité sur votre propre matériel, pendant le repos.
python -m vision.eval.evaluate ~/seances/2026-08-15/session_rest.json \
    --out-of-domain --out spec.json

# 4. Balayage en fps : le même tournage rejoué comme un appareil plus lent le
#    voit. C'est ce qui rend `kip_tolerance_ms` ajustable sans refilmer.
for f in 30 25 21 15; do
  python -m vision.eval.evaluate ~/seances/2026-08-15/session.json \
      --target-fps $f --out sens_${f}fps.json
done

# 5. Détail image par image, pour les seuils.
python -m vision.eval.evaluate ~/seances/2026-08-15/session.json \
    --dump-angles ~/seances/2026-08-15/csv
```

Envoyez `sens.json`, `spec.json` et les `sens_*fps.json`. Les vidéos restent chez
vous ; ces JSON ne contiennent que des nombres dérivés — c'est exactement la
frontière que l'architecture impose à l'app elle-même.

**Ce qu'on lira en premier**, dans cet ordre :

1. `detection.limb_ratio` et `limb_ratio_cv` sur `01_idle_tpose` — verdict M4.
2. `gate_recall` sur `session.json` — le portillon a-t-il enfin laissé passer
   une traction.
3. MAE / OBO sur les trois séries strictes — la sensibilité, pour la première
   fois.
4. `reps_invented_total` sur `session_rest.json`, et surtout sur le dead hang.
5. L'écart entre `sens_30fps` et `sens_21fps` — de combien les seuils temporels
   bougent entre le harnais et l'appareil.

**Aucun seuil ne bougera avant que ces chiffres existent.** C'est la règle que le
projet s'est donnée, et les quatre derniers tours ont montré ce qu'elle vaut :
trois diagnostics successifs, deux d'entre eux faux, tous portés sur la mauvaise
couche parce qu'aucune mesure ne venait d'un vrai athlète faisant un vrai
mouvement.
