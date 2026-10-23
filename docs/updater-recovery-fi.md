# PHP-päivitysvahdin asennus ja palautus uudelle koneelle

Tällä ohjeella korvataan päivitysvahti, jos nykyinen `tgi-ab-1`
(`192.168.31.201`) hajoaa. Ohje ei tarvitse vanhan koneen tiedostoja tai
yksityistä SSH-avainta. Uuden koneen IP-osoite ja nimi voivat olla erilaiset.

Vahti tarkistaa PHP 8.4- ja 8.5-haarojen korjausversiot 15 minuutin välein.
Varsinaiset AMD64/ARM64-buildit, testit ja GHCR-julkaisut tapahtuvat GitHub
Actionsissa. Vahtikoneelle ei tarvita Dockeria, AI-palvelua, sähköpostia tai
henkilökohtaista GitHub-tokenia.

Koneen rikkoutuminen keskeyttää uusien päivitysten tunnistamisen. Jo julkaistut
imaget, GitHubissa käynnissä olevat julkaisuajot ja asiakkaiden kontit jatkavat
toimintaansa siitä riippumatta.

## 1. Poista vanhan koneen kirjoitusoikeus

Avaa ylläpitäjän GitHub-tunnuksella:

https://github.com/codenamey/tgi-wordpress/settings/keys

Poista rikkoutuneen koneen deploy key. Alkuperäisen koneen avaimen nimi on
`TGI PHP updater - tgi-ab-1 (192.168.31.201)` ja ID `167476307`.
Myöhemmillä korvaavilla koneilla on omat avaimensa: poista sen koneen avain,
joka on poistumassa käytöstä. Älä poista muiden palveluiden avaimia.

Jos vanha kone vielä vastaa, pysäytä myös sen ajastus ja mahdollinen käynnissä
oleva tarkistus:

```bash
systemctl disable --now tgi-wordpress-updater.timer
systemctl stop tgi-wordpress-updater.service
```

Pidä vain yksi varsinainen päivitysvahti käytössä. Vanhan avaimen poistaminen
estää myös myöhemmin uudelleen käynnistyvää vanhaa konetta puskaamasta muutoksia.

## 2. Valmistele uusi kone

Seuraavat asennuskomennot ajetaan uuden **Debian 12 -koneen root-käyttäjänä**.
Nykyinen asennus käyttää tätä käyttöjärjestelmää ja systemd:tä. Tarkista myös,
että koneen kello ja DNS toimivat.

Tarvitaan GitHub-repositorion ylläpitäjän käyttöoikeus uuden julkisen avaimen
lisäämiseen kohdassa 4. Näitä ylläpitäjän tunnuksia ei asenneta vahtikoneelle.

Ulospäin pitää päästä HTTPS-yhteyksillä GitHubiin (`github.com`,
`api.github.com`, `raw.githubusercontent.com`), `www.php.net`-palveluun ja
Debian-imagen manifestitietoja varten Docker Hubiin (`auth.docker.io`,
`registry-1.docker.io`). Git-push tarvitsee SSH-yhteyden `github.com`:n porttiin
22. Internetistä sisään tulevaa webhookia tai HTTP-palvelua ei tarvita.

```bash
apt-get update
apt-get install -y ca-certificates git openssh-client python3

git clone --branch master https://github.com/codenamey/tgi-wordpress.git /root/tgi-wordpress-recovery
cd /root/tgi-wordpress-recovery
git rev-parse HEAD
```

Asennus on tarkoitettu tavalliseen systemd-palvelimeen, ei pelkkään
Docker-sovelluskonttiin. Pythonin pitää olla vähintään 3.9.

## 3. Asenna samat tiedostot kuin nykyisellä koneella

Kopioi seuraavat neljä tiedostoa samaan valmisteluhakemistoon. Tämä on tarpeen,
koska `automation/install.sh` odottaa `watch_updates.py`-tiedostoa ja unit-tiedostoja
omaan hakemistoonsa; sitä ei ajeta suoraan repositoryn automation-hakemistosta.

```bash
cd /root/tgi-wordpress-recovery
install -d -m 0755 /root/tgi-wordpress-updater-stage
cp scripts/watch_updates.py automation/install.sh automation/tgi-wordpress-updater.service automation/tgi-wordpress-updater.timer /root/tgi-wordpress-updater-stage/
sh /root/tgi-wordpress-updater-stage/install.sh
```

Skripti:

- Luo järjestelmäkäyttäjän `tgi-wp-updater`, jolla ei ole Docker-oikeuksia.
- Asentaa koodin tiedostoon `/opt/tgi-wordpress-updater/watch_updates.py`.
- Luo tilahakemiston `/var/lib/tgi-wordpress-updater/` oikeuksilla 0700.
- Luo uuden Ed25519-avaimen, ellei avainta jo ole tällä koneella.
- Hakee GitHubin SSH-palvelinavaimet GitHubin HTTPS-metadatasta.
- Asentaa ja tarkistaa systemd-palvelun ja ajastimen.

Skripti **ei vielä kytke ajastinta päälle**. Rekisteröi avain ja testaa ensin.
Yksityinen avain on `/var/lib/tgi-wordpress-updater/deploy_key`; älä tulosta tai
kopioi sitä GitHubiin tai keskusteluun. Avaimen kommentissa voi näkyä alkuperäisen
asennuksen nimi `tgi-ab-1`; se on vain tunniste, ei sidonta koneeseen tai IP:hen.

## 4. Rekisteröi uuden koneen julkinen avain

Tulosta vain **julkinen** avain:

```bash
cat /var/lib/tgi-wordpress-updater/deploy_key.pub
```

Omalla ylläpitäjän työasemallasi selaimessa:

1. Avaa https://github.com/codenamey/tgi-wordpress/settings/keys .
2. Valitse **Add deploy key**.
3. Anna kuvaava nimi, esimerkiksi `TGI PHP updater - uusi-kone`.
4. Liitä uuden koneen `.pub`-tiedoston koko sisältö.
5. Valitse **Allow write access** ja tallenna.

Kirjoitusoikeus tarvitaan versiopäivityksen Git-pushiin. Avain liitetään vain
`codenamey/tgi-wordpress`-repositorioon. GHCR:n julkaisutunnusta ei tarvita
vahtikoneella: Actions käyttää omissa ajoissaan lyhytikäistä `GITHUB_TOKEN`:ia.

## 5. Testaa yhteydet ja tarkistus ilman julkaisua

Testaa uuden avaimen SSH-yhteys juuri oikeaan repositoryyn. Komento lukee
ainoastaan HEAD-viitteen eikä tee muutoksia:

```bash
runuser -u tgi-wp-updater -- env GIT_SSH_COMMAND='ssh -i /var/lib/tgi-wordpress-updater/deploy_key -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=/var/lib/tgi-wordpress-updater/known_hosts' git ls-remote git@github.com:codenamey/tgi-wordpress.git HEAD
```

Tuloksena pitää näkyä commit-tunnus ja `HEAD`. Tämä todentaa yhteyden;
kirjoitusoikeuden **Allow write access** -valinta tarkistetaan erikseen GitHubista.

Aja sitten oikea upstream-tarkistus ilman commitia tai pushia:

```bash
runuser -u tgi-wp-updater -- python3 /opt/tgi-wordpress-updater/watch_updates.py --check
```

Onnistunut uusi asennus tulostaa JSON-tuloksen, jossa `action` on `check_only`.
`update.changed` on `false`, jos uusia PHP-korjausversioita ei ole, tai `true`,
jos uusi sallittu korjausversio löytyi. Kumpikaan tulos ei tässä tarkistustilassa
puske muutoksia tai käynnistä julkaisua. Yhteys- tai validointivirhe pitää
selvittää ennen ajastuksen kytkemistä päälle.

## 6. Kytke automaatio päälle

```bash
systemctl enable --now tgi-wordpress-updater.timer
systemctl start tgi-wordpress-updater.service

systemctl is-enabled tgi-wordpress-updater.timer
systemctl is-active tgi-wordpress-updater.timer
systemctl list-timers tgi-wordpress-updater.timer --no-pager
systemctl show tgi-wordpress-updater.service -p Result -p ExecMainStatus
cat /var/lib/tgi-wordpress-updater/status.json
journalctl -u tgi-wordpress-updater.service -n 30 --no-pager
```

Tarkista:

- Ajastin on `enabled` ja `active`, ja seuraava ajo näkyy listalla.
- Tarkistus päättyi arvoihin `Result=success` ja `ExecMainStatus=0`.
- `status.json` sisältää tuoreen UTC-aikaleiman ja esimerkiksi `up_to_date`,
  `published_update_commit` tai `waiting_for_release` tilanteen mukaan.

Palvelu on `Type=oneshot`, joten sen `inactive (dead)` -tila onnistuneiden ajojen
välissä on normaali. Ajastimen pitää jäädä aktiiviseksi.

Tämä vaihe voi jo puskea uuden sallitun PHP-päivityksen ja käynnistää julkaisun,
jos sellainen löytyi. Se ei deployaa asiakassivustoille eikä lähetä sähköpostia.

## 7. Tarkista myös GitHubin julkaisut

Avaa https://github.com/codenamey/tgi-wordpress/actions/workflows/release.yml .
Tarkista mahdollisen käynnissä olevan tai viimeksi epäonnistuneen julkaisun tila.
Vahtikoneen `up_to_date` tarkoittaa lähdeversioiden vastaavuutta Git-lukkoon;
se ei yksin todista, että viimeisin imagejulkaisu onnistui.

Jos vanha kone ehti puskea version ennen rikkoutumistaan, GitHubin julkaisu voi
edelleen olla käynnissä. Se jatkuu ilman vanhaa vahtia. Jos julkaisu epäonnistui,
selvitä sen virhe GitHubissa; uusi vahti ei rakenna samaa jo lukittua PHP-versiota
uudelleen vain siksi, että kone vaihdettiin. Julkaisun voi uusia GitHubin
**Run workflow** -toiminnolla oikeasta source-tilasta ja omistajalla `codenamey`,
repositoryn näkyvyydellä `public` sekä nimenomaisella publish-valinnalla.
Manuaalinen julkaisu käyttää Git-lukon versiota, eikä itsessään hae uutta PHP:tä.

Toimivan julkaisun latauksen voi tarkistaa erillisellä Docker-koneella:

```bash
docker pull ghcr.io/codenamey/tgi-wordpress:8.4-latest
docker pull ghcr.io/codenamey/tgi-wordpress:8.5-latest
```

GitHub Actionsin on oltava käytössä ja `ghcr-release`-ympäristön sekä GHCR-paketin
oikeuksien kunnossa. Ympäristöön asetetut required reviewers -vaatimukset
pysäyttävät julkaisun hyväksyntää odottamaan. Uusi kriittinen havainto tai
vanhentunut tietoturvapoikkeus pysäyttää julkaisun myös uudella vahtikoneella;
palautus ei saa ohittaa näitä portteja.

## Mitä tarvitsee varmuuskopioida?

Vahtikoneen levyvarmuuskopio on hyödyllinen, mutta ei tämän palautuksen edellytys:

- Koodi, unit-tiedostot, hyväksytty versiolukko ja julkaisutiedot ovat GitHubissa.
- Julkaistut imaget ja niiden digestit ovat GHCR:ssä ja julkaisumuistioissa.
- SSH-avain voidaan luoda uudelleen ja vanha avain poistaa käytöstä.
- `status.json`, lokit ja tilapäiset kloonit eivät ole pakollisia palautettavia
  tiedostoja. Mahdollinen keskeneräinen julkaisu tarkistetaan GitHubista.

Asiakkaiden tietokannat ja WordPress-volumet eivät sijaitse päivitysvahdissa.
Niiden varmuuskopiointi kuuluu tuotantopalvelimien omaan palautussuunnitelmaan.
Katso myös [automaation toimintakuvaus](automatic-updates.md) ja
[julkaistu r4](release-2026-10-24-r4.md).
