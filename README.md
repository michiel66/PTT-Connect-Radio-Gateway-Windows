# PTT Connect Radio Gateway — Windows Desktop Test

Een Windows desktop-app **zonder browser**. Ondersteunt keuze voor een ingebouwde of USB-geluidskaart, ingangsniveaumeter, VOX-test en het opslaan van instellingen. TeamSpeak-adres, bijnaam en kanaal zijn instelbaar.

**Beperking:** er is nog geen TeamSpeak voice client aanwezig. De knop Verbinden meldt dit eerlijk. Er wordt geen audio verzonden of ontvangen via TeamSpeak. De audiotest leest uitsluitend de microfoon/line-in. De uitgangskeuze is voorbereid, maar uitvoer wordt nog niet gebruikt. RTL-SDR en crosslink staan op de roadmap, nog niet in deze versie.

## Lokaal starten

Windows 10/11, Python 3.12:

```powershell
py -m pip install -r requirements.txt
py main.py
```

## EXE maken met GitHub

Upload alle projectbestanden inclusief `.github` in een nieuwe repository. Open **Actions → Bouw Windows EXE → Run workflow**. Na afloop kun je onder **Artifacts** het Windows-programma downloaden.

## Veiligheid

Laat geen zendapparatuur via VOX zenden tijdens de eerste audiotests. Voor radio-koppeling zijn correcte line-level-aanpassing en bescherming tegen terugkoppeling nodig. Er is geen uitzending via deze prototype-app.
