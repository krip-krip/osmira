# 0011 — Source d'une caméra : serveur média ou direct, URL calculée ou imposée

- Statut : Accepté
- Date : 2026-11-27

## Contexte
Jusqu'ici, une caméra n'avait qu'une URL SRT saisie à la main. L'exploitation
veut choisir d'abord d'où vient l'image (un chemin d'un MediaMTX déclaré, ou
la caméra elle-même), sans retaper d'URL, tout en gardant la main pour les cas
particuliers (NAT, relais, réglage inhabituel).

## Décision
- Une caméra a une **source** :
  - `media_server` : un serveur média déclaré + un chemin MediaMTX ; le poste
    est caller vers l'**adresse SRT du serveur** (`srt_address`, nouveau champ
    du serveur, détectable dans la config MediaMTX) ;
  - `direct` : la caméra elle-même, poste **caller** (il appelle `hôte:port`)
    ou **listener** (il attend la caméra sur `port`, hôte facultatif).
- Le Core **calcule** l'URL :
  `srt://<srt_address>?mode=caller&streamid=read:<chemin>`,
  `srt://<hôte>:<port>?mode=caller`, `srt://[<hôte>]:<port>?mode=listener`.
- Dans tous les modes, une **URL imposée** (override) remplace l'URL calculée ;
  la retirer revient à l'URL calculée. Renvoyer l'URL calculée elle-même n'est
  pas un override (une lecture recopiée dans une écriture ne fige rien).
- L'URL effective est enregistrée avec la caméra et recalculée quand la source
  ou l'adresse SRT du serveur change ; seule l'URL effective part aux postes.
- Un serveur média utilisé par des caméras ne peut pas être supprimé.
- Les médias exposés par un serveur sont lus **en direct** dans son API
  (chemins, état, codec, taille, lecteurs) pour aider la saisie.

## Options écartées
- **URL toujours saisie à la main** : erreurs de frappe, rien ne suit un
  changement d'adresse du serveur.
- **URL calculée seulement, sans override** : bloquant derrière un NAT ou un
  relais (cas du relais `.252`).
- **Adresse SRT déduite à chaque lecture depuis MediaMTX** : la configuration
  des postes dépendrait de la joignabilité de MediaMTX depuis le Core ;
  l'adresse est donc enregistrée, la détection n'est qu'une aide.

## Conséquences
- Mode listener : une seule station peut recevoir une caméra de cette façon ;
  comportement de `ptzview` en attente d'appel à vérifier sur le matériel.
- Les statistiques SRT rattachent une caméra « via serveur » par son serveur et
  son chemin, sans analyser l'URL.
- Schéma de base modifié : une base créée avant doit être recréée (pas encore
  de migrations, ADR 0008).
