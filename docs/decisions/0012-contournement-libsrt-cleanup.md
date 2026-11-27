# 0012 — Contournement du décompte `srt_startup`/`srt_cleanup` de libsrt 1.5.4

- Statut : Accepté
- Date : 2026-11-28

## Contexte
Essai de 30 min du 27/11 et essais d'exploitation : quand une seule entrée de
`ptzview` se ferme (flux calé) ou échoue à se connecter (caméra absente,
entrée désassignée), **toutes les autres connexions SRT se coupent** en même
temps (`EID … no sockets to check, this would deadlock`), puis se
reconnectent ; avec une entrée qui échoue en boucle, NO SIGNAL clignote sans
fin.

Cause, lue dans le code de libsrt 1.5.4 (Debian trixie) : `srt_startup()`
retourne avant d'incrémenter son compteur dès que la bibliothèque tourne,
alors que chaque `srt_cleanup()` le décrémente. FFmpeg (`libsrt.c`) appelle
`srt_startup()` à chaque ouverture et `srt_cleanup()` à chaque fermeture ou
échec : la première fermeture ramène le compteur à 0 et arrête libsrt pour
tout le processus.

## Décision
`ptzview` définit sa propre fonction `srt_cleanup()` qui ne fait rien, et est
lié avec `-rdynamic` pour que libavformat l'appelle à la place de celle de
libsrt. La bibliothèque reste démarrée pendant toute la vie de `ptzview` ; le
système libère tout à la sortie. Les sockets fermés restent libérés par le
ramasse-miettes de libsrt.

## Options écartées
- **Mettre à jour libsrt** : version imposée par la distribution ; à revoir
  quand une version corrigée sera disponible (le contournement reste
  inoffensif).
- **Un processus par entrée** : environ 2,5 fois plus de RAM et de CMA (ADR 0001).
- **Remplacer le protocole SRT de FFmpeg** par une lecture libsrt directe :
  beaucoup de C pour le même résultat.

## Conséquences
- Mesuré sur le Pi (3 entrées valides + 1 injoignable, 25 s) : 21 coupures
  des bonnes entrées avant, 0 après.
- Dépend du nom de symbole `srt_cleanup` ; si FFmpeg ou libsrt changent ce
  comportement, revoir ce contournement.
