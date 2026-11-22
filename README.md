# veille-feeds

Collecte automatique pour la veille quotidienne de Luke.

Chaque nuit (3 créneaux entre 1h et 4h UTC), une GitHub Action lit les flux RSS et les chaînes YouTube listés dans `sources.json`, garde seulement les nouveautés et écrit :

- `digest/latest.md` : le digest compact lu par la veille Claude à 6h40 ;
- `digest/status.md` : l'état de chaque flux (OK ou erreur) ;
- `digest/archive/` : les 14 derniers digests.

Ajouter une source : une ligne dans `sources.json` (`rss` avec une URL, ou `youtube` avec le @handle de la chaîne). Lancer à la main : onglet **Actions** → **Collecte veille** → **Run workflow**.
