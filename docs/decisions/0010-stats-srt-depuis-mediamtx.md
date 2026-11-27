# 0010 — Statistiques SRT lues par le Core dans l'API MediaMTX

- Statut : Accepté
- Date : 2026-11-27

## Contexte
Il faut mesurer la robustesse des liaisons SRT (pertes, retransmissions,
paquets jetés, RTT, débit) et garder l'historique pour comparer des essais.
Deux liaisons par image : caméra → MediaMTX et MediaMTX → poste. MediaMTX
(v1.21) expose déjà ces compteurs pour les deux, côté récepteur pour la
première, côté émetteur pour la seconde. Les postes passent par un relais
(`192.168.104.252`) : MediaMTX voit l'adresse du relais, pas celle du Pi.

## Décision
- Nouvelle entité **serveur média** (MediaMTX) : adresse de l'API, identifiants
  facultatifs (mot de passe en écriture seule), activée ou non.
- Le Core lit l'API de chaque serveur **en lecture seule** toutes les 5 s
  (`paths/list`, `paths/static-sources/get/<chemin>`, `srtconns/list`) et
  stocke un relevé par liaison dans SQLite (table `srt_samples`, compteurs
  cumulés tels que donnés par MediaMTX), gardé 7 jours (réglable).
- **Caméra** d'une liaison : par l'URL SRT de la caméra (même hôte que l'API,
  chemin pris dans `streamid=read:<chemin>`).
- **Poste** d'une liaison : l'agent ajoute `station=<id>` à son streamid
  (`read:cam1:::station=panelTest`) ; MediaMTX l'affiche dans le champ `query`
  de la connexion. Vérifié sur MediaMTX v1.21.4. Réglable (`tag_srt_streamid`).
- Le codec, la taille et l'état « prêt » de chaque chemin MediaMTX servent
  aussi à la page Cameras (format vu par le serveur).
- Rien de temps réel n'en dépend : serveur injoignable → seules ses
  statistiques s'arrêtent, signalé dans la page Media servers.

## Options écartées
- **Retrouver le poste par son adresse IP** : faux derrière le relais/NAT.
- **Statistiques SRT lues sur le Pi** : FFmpeg n'expose pas les statistiques
  libsrt à `ptzview` sans modifier le C ; le Pi remonte déjà les symptômes
  (i/s, erreurs de décodage, reconnexions) dans son état.
- **Prometheus / InfluxDB** : composants de plus à installer ; SQLite suffit
  pour quelques dizaines de liaisons à 5 s (≈ 140 000 lignes par jour pour 8
  liaisons).
- **Stocker des taux plutôt que des compteurs** : les compteurs cumulés
  permettent de recalculer n'importe quel intervalle.

## Conséquences
- Le Core doit pouvoir joindre l'API MediaMTX (port 9997) ; si le Core est
  sur un VPS, il faudra une route (NetBird) ou un relais local.
- MediaMTX donne les pertes MediaMTX → poste vues par l'émetteur ; les paquets
  jetés côté Pi (`RCV-DROPPED`) restent visibles par l'état du poste
  (erreurs de décodage).
- La base grossit : purge automatique au-delà de la durée de conservation ;
  les sessions de mesure (6c) devront être protégées de cette purge.
