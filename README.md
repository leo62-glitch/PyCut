# PyCut (REA Claude Fable)

Éditeur vidéo de bureau inspiré de CapCut, 100 % Python (PySide6 + OpenCV). Projet indépendant, sans lien avec CapCut/ByteDance.

## Lancer (Windows)
```powershell
cd PyCut
pip install PySide6 numpy opencv-python
python run.py
```
Optionnel : installer **ffmpeg** (dans le PATH) pour avoir l'audio à l'export et des infos média plus précises.
`python run.py "<dossier projet PyCut ou brouillon CapCut>"` ouvre directement un projet.

## Ce qui fonctionne
- Accueil : création de projet, liste de tes projets PyCut **et de tes brouillons CapCut** (lecture seule, ouverture = copie importée)
- Éditeur : médiathèque (import, glisser-déposer), lecteur (aperçu image par image, lecture), timeline complète
  (déplacer, rogner, diviser, dupliquer, copier/coller, superpositions, pistes texte/audio, aimantation, zoom, repères),
  inspecteur (position, échelle, rotation, opacité, volume, fondus, vitesse, inversion, réglages couleur, texte)
- Annuler/Rétablir, enregistrement automatique, export vidéo MP4, export/import des brouillons CapCut
- Raccourcis : Espace, Ctrl+Z / Ctrl+Maj+Z, Ctrl+B (diviser), Suppr, Ctrl+C/V/D, ←/→ (image), Home/End, Q/W (rogner), S (aimant), M (repère), Ctrl+E, Ctrl+S

## Pas encore (affiché « bientôt disponible »)
Transitions, effets, filtres, masques, chroma, stickers, légendes automatiques, animations, fonctions IA, enregistrement micro,
lecture du son dans l'aperçu (l'audio est mixé à l'export seulement), formes d'onde réelles.

## Brouillons CapCut
```
python tools/capcut_check.py            # teste l'import/export sur TOUS tes brouillons (lecture seule)
python tools/capcut_check.py "<dossier du brouillon>"
```
Menu → Fichier → *Exporter vers un brouillon CapCut…* (ferme CapCut avant). Les éléments du store CapCut (transitions, effets,
masques…) sont conservés tels quels à l'import mais ne peuvent pas être créés depuis PyCut ; ils sont signalés à l'export.

## Tests
`pip install pytest && python -m pytest -q` (23 tests, dont des tests d'interface en mode offscreen)
