# Mesures — changements de caméras sans coupure (2026-11-28)

`panelTest`, 4 caméras via MediaMTX, cam1 à l'écran pendant tout l'essai.
`ptzview` avec contournement libsrt (ADR 0012) et route `/input/N` ; agent
avec entrées stables. Actions faites dans le Core (API), comme depuis la page
Stations / Cameras.

| Action | Effet sur le Pi | Relance de ptzview | Coupures cam1 / cam4 |
|---|---|---|---|
| Renommer cam2 (non affichée) | libellé de l'entrée 2 | non | 0 / 0 |
| cam2 → autre chemin MediaMTX | entrée 2 reconnectée en 0,19 s | non | 0 / 0 |
| Retirer cam3 de la station | entrée 3 désactivée, aucune tentative pendant 20 s | non | 0 / 0 |
| Remettre cam3 | entrée 3 reconnectée en 0,07 s | non | 0 / 0 |
| Restaurer cam2 | entrée 2 reconnectée en 0,11 s | non | 0 / 0 |

Aucune erreur `no sockets to check` ; placement des caméras inchangé
(`["cam1", "cam2", "cam3", "cam4"]`).

Avant (27/11) : chaque changement relançait `ptzview` (coupure de l'image),
et une entrée retirée faisait clignoter NO SIGNAL sur toutes les entrées.

## Latence par entrée (même jour, PR suivante)

Entrée 3 = cam5 (chemin absent de MediaMTX : connexions refermées en boucle),
cam2 à l'écran. Latence de cam5 passée de 20 à 40 ms puis revenue à 20 ms
dans le Core : seule l'entrée 3 se reconnecte (`latence changée (40 ms)`),
**0 relance de ptzview, 0 coupure** des entrées 1, 2 et 4, aucune erreur
`no sockets to check` malgré l'entrée 3 qui échoue en boucle.
