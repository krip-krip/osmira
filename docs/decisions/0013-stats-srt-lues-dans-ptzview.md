# 0013 — Statistiques SRT côté réception lues dans `ptzview`

- Statut : Accepté
- Date : 2026-11-28

## Contexte
Les statistiques SRT viennent de MediaMTX (ADR 0010). Pour la liaison
MediaMTX → poste, MediaMTX est l'émetteur. Il voit les pertes et les
retransmissions, mais pas les paquets que le Pi **jette** parce qu'ils sont
arrivés trop tard (`dropped`). Ce sont eux qui abîment l'image. Les liaisons
directes caméra → poste (ADR 0011) n'ont aucune statistique SRT. Premier
relevé du 27/11 : 7 à 8,5 % de pertes vues par MediaMTX vers le Pi, sans
savoir combien sont rattrapées.

FFmpeg ne donne pas le socket libsrt de ses entrées SRT.

## Décision
- `ptzview` définit `srt_connect()` (mode caller) et `srt_accept()` (mode
  listener). Elles appellent les vraies fonctions de libsrt
  (`dlsym(RTLD_NEXT, …)`) et notent le socket dans l'entrée en cours
  d'ouverture. Une variable propre au thread indique l'entrée : FFmpeg ouvre
  l'entrée dans le thread qui appelle `avformat_open_input()`. C'est le même
  mécanisme `-rdynamic` que l'ADR 0012.
- `/status` donne, pour chaque entrée, un bloc `srt` lu par
  `srt_bistats()` : RTT, débit, capacité estimée, latence négociée, tampon,
  paquets reçus, perdus, retransmis, jetés, en retard (compteurs cumulés
  depuis la connexion), ou `null` si l'entrée n'est pas connectée.
- L'agent transmet ce bloc tel quel dans son état. Le Core le stocke avec les
  autres relevés du poste.
- Compilation : `libsrt-gnutls-dev` (en-têtes de la libsrt déjà chargée par
  FFmpeg). Aucune nouvelle bibliothèque à l'exécution.

## Options écartées
- **Lire le socket dans les structures privées de FFmpeg** (`URLContext`,
  `SRTContext`) : leur disposition change d'une version de FFmpeg à l'autre,
  plantage silencieux à la mise à jour.
- **Remplacer le protocole SRT de FFmpeg par une lecture libsrt directe** :
  beaucoup de C pour obtenir le même résultat (déjà écarté dans l'ADR 0012).
- **Se contenter des symptômes** (i/s, erreurs de décodage) : ils ne disent
  pas si le problème vient du réseau ou du décodage.

## Conséquences
- Dépend des noms de symboles `srt_connect` et `srt_accept`, utilisés par
  FFmpeg (`libsrt.c`). Si FFmpeg change sa façon d'ouvrir le SRT, `srt`
  restera à `null` sans rien casser d'autre.
- L'option « statistiques lues sur le Pi » de l'ADR 0010 n'est plus écartée.
  Les deux sources se complètent : émetteur (MediaMTX), récepteur (poste).
