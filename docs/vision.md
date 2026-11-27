# Vision et contraintes

## But

Permettre à des cadreurs de piloter à distance des caméras PTZ, depuis un poste
simple (Raspberry Pi + écran HDMI + manette), avec un retour vidéo de qualité
broadcast et une latence la plus faible possible. Le tout est configuré et
supervisé depuis un serveur central.

## Priorités (dans cet ordre)

1. **Latence de bout en bout (glass-to-glass) minimale.** Objectif : 150 à 200 ms.
2. **Bascule instantanée entre caméras** : à l'image suivante, sans attendre
   d'image clé.
3. **Fiabilité** : un poste continue de fonctionner (image + pilotage) même si
   le serveur central est injoignable.
4. **Extensibilité** : ajouter une marque de caméra, un type de manette ou un
   nouveau module sans réécrire l'existant.

## Périmètre

### OsmiraCam (poste cadreur)
- Reçoit en permanence les flux SRT/H.265 des caméras autorisées et les décode
  tous en continu ; affiche la caméra sélectionnée en plein écran HDMI.
- Calques dessinés à l'affichage (jamais incrustés par le CPU dans l'image) :
  bordure tally (rouge PGM, vert PVW), bandeau UMD, « NO SIGNAL ».
- Pilote en direct la caméra affichée avec une manette (PS4 en USB au départ ;
  d'autres manettes ensuite, mappage libre).
- Reçoit sa configuration, ses droits, le tally et l'UMD d'OsmiraCore.

### OsmiraCore (serveur central)
- Tourne sur Linux, n'importe où (domicile, VPS) : pas forcément proche des caméras.
- Interface web dès le départ.
- Décrit les caméras (paramètres média + paramètres de contrôle), les sites,
  les postes, les profils de manette et les droits (voir / décoder / piloter).
- Envoie à chaque poste sa configuration, le tally et l'UMD.
- Ne transporte ni vidéo ni commande PTZ.

### Plus tard
- Modules de récupération du tally (mélangeur, autre contrôleur…).
- Postes de réalisation, de mixage, etc.
- Plusieurs sites.

## Contraintes

- Pas de limite fixée au nombre d'opérateurs ni de caméras.
- Caméras : Panasonic AW-UE150 pour les tests, puis Sony FR7, Canon, etc.
- Raspberry Pi 4 à 1 Go de RAM : outils sobres (ni navigateur, ni compositeur,
  ni bureau) ; mémoire CMA limitée.
- Production en 1080i50 ; flux IP progressifs 1080p50 ou 1080p25.
- Réseau : sites reliés par VPN WireGuard (NetBird).

## Hors périmètre (pour l'instant)

- Authentification forte / multi-tenant.
- Enregistrement, ré-encodage, mélange vidéo.
- Lancement automatique au démarrage (systemd) : viendra après la maquette.
