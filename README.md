# iaCoach

Coach de street workout / calisthenics pour athlète seul, équipé d'un téléphone.
Comptage de répétitions et contrôle qualité **sur l'appareil**, débrief par LLM.

> **État : M0 livré, architecture en attente de validation.**
> Le plan complet est dans [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md), les
> jalons dans [`docs/ROADMAP.md`](docs/ROADMAP.md). M1+ n'est pas commencé.

---

## Le principe

Trois couches, séparées par une contrainte de latence, pas par goût :

1. **Temps réel, dans le navigateur.** Caméra → MediaPipe Pose Landmarker →
   angles 3D → FSM de comptage → scores de qualité. Aucun appel réseau dans la
   boucle : la fenêtre de correction utile est ~100 ms, un aller-retour cloud en
   coûte 150–400.
2. **Asynchrone, backend Python.** Persistance, débrief coach, analyse de clips
   uploadés par un modèle de pose plus lourd.
3. **Fine-tuning, sur PC/RTX.** Corrige le décrochage des modèles génériques sur
   les postures difficiles (muscle-up, front lever, occlusions). Sert l'analyse
   serveur, jamais le temps réel.

Ce qui différencie ce projet des templates « AI gym trainer » : le retour n'est
pas binaire. Une rep produit un `RepEvent` complet — amplitude, symétrie,
kipping, tempo, alignement — chacun **continu dans `[0,1]`**, pas un `true/false`.
« Tu ne descends pas assez bas sur les 3 dernières » plutôt que « rep invalide ».

### Confidentialité

Aucune image ni vidéo ne quitte l'appareil. Seules les métriques numériques
agrégées partent vers l'API Anthropic. Sans clé API, tout fonctionne sauf le
débrief.

---

## Lancer

### PWA (temps réel)

```bash
cd web
npm install
npm run dev          # http://localhost:5173
```

`getUserMedia` exige un contexte sécurisé : `localhost` suffit sur desktop.
Pour tester depuis un téléphone sur le LAN, il faut du HTTPS (certificat local
ou tunnel).

Optionnel, pour l'offline-first : `npm run fetch-model` vendore le modèle de pose
dans `public/models/` au lieu de le charger depuis un CDN.

### Backend (coaching, persistance)

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp ../.env.example ../.env        # y mettre ANTHROPIC_API_KEY
uvicorn iacoach.api.app:app --reload
```

`GET /health` indique si la couche coaching est active.

### Tests

```bash
cd backend && pytest && ruff check src tests
cd web && npm test && npm run typecheck
```

---

## Structure

| Chemin | Rôle |
|---|---|
| `web/` | PWA : caméra, pose temps réel, comptage, UI |
| `backend/src/iacoach/contracts.py` | **Source de vérité des contrats de données** |
| `contracts/schema/` | JSON Schema générés (ne pas éditer à la main) |
| `web/src/types/contracts.ts` | Miroir TypeScript des contrats |
| `prompts/coaching.md` | System prompt du coach, versionné |
| `vision/finetune/` | Pipeline de fine-tuning pose (PC/RTX), M4 |
| `docs/BENCHMARKS.md` | Journal des mesures — aucune perf revendiquée sans ligne ici |

Les contrats sont générés depuis Pydantic ; un changement de modèle non
répercuté fait échouer la CI plutôt que de dériver en silence.
