# Mesures — premières statistiques SRT lues dans MediaMTX (2026-11-27)

Core sur le PC (`10.7.1.63`), collecte toutes les 5 s dans l'API MediaMTX
v1.21.4 (`192.168.104.253:9997`) ; agent + `ptzview` sur `panelTest` avec
connexions signées `station=panelTest`. Latence SRT 20 ms, 4 × H.265 1080p50.
Relevé après ~25 s de fonctionnement (intervalle de 5 s).

| Liaison | RTT | Débit | Pertes (5 s) | Retransmissions | Jetés |
|---|---|---|---|---|---|
| cam1–4 → MediaMTX (`192.168.105.51–54:2020`) | 0,8–1,1 ms | 15,6–16,6 Mb/s | 0 % | 0/s | 0 |
| MediaMTX → `panelTest` (vu depuis `192.168.104.252`) | 5,3–6,0 ms | 17,2–18,0 Mb/s | **6,9–8,5 %** | 123–153/s | 0 |

- Les pertes sont sur le trajet MediaMTX → Pi (relais `.252` + VPN), pas côté
  caméras. Avec 20 ms de latence et ~6 ms de RTT, les retransmissions les
  rattrapent à cet instant (aucun paquet jeté côté émetteur).
- Les connexions du Pi arrivent toutes depuis `192.168.104.252` : la signature
  du streamid est indispensable pour les attribuer au poste.
- À faire : endurance (30 min et plus) avec sessions de mesure, comparer
  latence 20 / 40 ms, et chemin direct sans relais.
