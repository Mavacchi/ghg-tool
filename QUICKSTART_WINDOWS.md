# Quickstart Windows — senza terminale

Guida passo-passo per avviare il GHG Tool su Windows con il minimo numero
di click e senza scrivere comandi nel terminale.

---

## Cosa serve

1. **Windows 10/11** (64 bit) — va bene anche Windows 11 ARM con WSL.
2. **Docker Desktop** — motore che esegue il software.
3. **Connessione internet** alla prima esecuzione (per scaricare le
   immagini di base, circa 600 MB totali).
4. **8 GB di RAM** liberi consigliati.
5. **Spazio disco**: circa 2 GB per immagini Docker + dati.

---

## Passo 1 — Installa Docker Desktop

1. Vai su <https://www.docker.com/products/docker-desktop/>.
2. Clicca **"Download for Windows"**.
3. Avvia il file scaricato (`Docker Desktop Installer.exe`).
4. Accetta le impostazioni di default (lascia attiva l'opzione *Use WSL 2
   instead of Hyper-V* se richiesta).
5. Riavvia il PC quando l'installer lo chiede.
6. Dopo il riavvio, apri **Docker Desktop** dal menu Start.
7. Aspetta che l'icona della balena (in basso a destra, nella system tray)
   diventi stabile. Può volerci 1-2 minuti la prima volta.

> Se Docker chiede di accettare il *Subscription Service Agreement*, accetta.
> Per uso personale e small business (<250 dipendenti, <10M USD fatturato)
> Docker Desktop è gratuito.

---

## Passo 2 — Scarica il progetto

1. Vai su <https://github.com/mavacchi/ghg-tool>.
2. Clicca sul menù a tendina **Branch** in alto a sinistra e seleziona
   `claude/ghg-emissions-calculator-NFJZW` (oppure `main` se già fuso).
3. Clicca il bottone verde **Code** → **Download ZIP**.
4. Una volta scaricato il file `ghg-tool-...zip`, doppio click per aprirlo.
5. Estrai la cartella in un percorso semplice, per esempio:
   `C:\Users\<TuoNome>\Desktop\ghg-tool`.

---

## Passo 3 — Primo avvio

1. Apri la cartella estratta.
2. **Doppio click su `start.bat`**.
3. Se Windows mostra un avviso *Windows ha protetto il PC*, clicca
   **Ulteriori informazioni → Esegui comunque**. (Lo script è sicuro,
   l'avviso compare per qualsiasi `.bat` non firmato.)
4. Si apre una finestra nera (Prompt dei comandi) che mostra il
   progresso. La prima volta scarica le immagini di base e costruisce
   l'ambiente: **3-5 minuti**.
5. Quando lo script ha finito:
   - Si apre automaticamente il browser su <http://localhost:8501>.
   - La finestra nera resta aperta con il messaggio *Tutto pronto*.
6. Per chiudere la finestra nera premi un tasto qualsiasi. I container
   continuano a girare in background.

---

## Passo 4 — Usa la dashboard

La dashboard ha 8 pagine, accessibili dalla sidebar di sinistra:

| # | Pagina | Cosa mostra |
|---|---|---|
| 0 | **Home** | KPI totali Scope 1/2 LB/MB/3, memo biogenico separato, banner VIANO 2025 |
| 1 | **Drill down** | Esplora emissioni per sito × scope × sotto-scope × anno |
| 2 | **YoY comparison** | Confronto anno su anno (2024 vs 2025), variazioni assolute e percentuali |
| 3 | **Intensity metrics** | tCO2e per EUR, per m², per FTE, per kg prodotto |
| 4 | **Factor catalog** | Browse del catalogo fattori di emissione (DEFRA/ISPRA/IPCC/ecoinvent) versionato |
| 5 | **DQ findings** | Problemi di qualità dati, workflow di waiver |
| 6 | **Audit trail** | Storia di ogni record di emissione (predecessor → correzione) |
| 7 | **Reports export** | Genera PDF (ESRS E1-6 + E1-7) o Excel multi-foglio |

La documentazione API (per sviluppatori) è su <http://localhost:8000/docs>.

> **NB**: al primo avvio il database è vuoto. La pipeline di caricamento
> dati reali (ETL) richiede file Excel formato Saturnia che non sono
> inclusi nel repository. Senza dati, le pagine mostreranno *Nessun dato
> disponibile* o *MV not yet populated* in modo elegante.

---

## Passo 5 — Fermare il programma

Quando hai finito:

- **Doppio click su `stop.bat`** nella stessa cartella.
- Lo script ferma tutti i container ma **mantiene i dati** nel volume
  Docker `ghg_pgdata`.
- Al prossimo `start.bat` il programma riparte in pochi secondi con i
  dati di prima.

Se vuoi cancellare anche i dati (resettare tutto a zero), apri Docker
Desktop → *Volumes* → trova `ghg_pgdata` → click sul cestino.

---

## Risoluzione problemi

### *Docker Desktop non si avvia*

- Riavvia il PC.
- Verifica che la virtualizzazione sia abilitata nel BIOS (cerca *VT-x*
  per Intel o *AMD-V*).
- Su Windows Home, Docker Desktop richiede WSL 2: aprilo dal menu Start
  e segui la procedura guidata. In alternativa segui la guida ufficiale
  <https://docs.docker.com/desktop/install/windows-install/>.

### *La porta 5432, 8000 o 8501 è già in uso*

Qualcun altro sulla tua macchina sta usando quelle porte. Le più comuni:

- **5432** — hai un PostgreSQL già installato. Spegnilo dai servizi
  Windows, oppure modifica `docker-compose.yml` cambiando `"5432:5432"`
  in `"5433:5432"`.
- **8000** — spesso usata da Django/altri server di sviluppo. Chiudili.
- **8501** — hai un'altra istanza Streamlit aperta. Chiudila.

### *Il browser si apre ma vedo* “This site can't be reached”

- Aspetta altri 30 secondi e ricarica la pagina. La dashboard impiega
  un po' a partire la prima volta.
- Se non riparte: apri Docker Desktop → *Containers* → verifica che
  `ghg_db`, `ghg_migrate`, `ghg_app`, `ghg_streamlit` siano tutti
  *Running*. Se uno è *Exited (error)* clicca sul nome e leggi i log.

### *Le pagine sono in inglese ma le voglio in italiano (o viceversa)*

La sidebar della dashboard ha un selettore di lingua (IT/EN). Le
traduzioni sono caricate da `it.json` e `en.json` (110 chiavi ciascuna,
verificate in parità al commit `f578832`).

### *Voglio caricare dei dati di test*

La pipeline ETL non è ancora wired-up per i file Excel di Saturnia
(scheduled per v1.1, vedi `docs/roadmap.md`). Per il momento puoi
usare la dashboard solo per esplorare la UI e l'API; per dati reali
serve l'intervento di uno sviluppatore.

---

## Riepilogo file

| File | A cosa serve |
|---|---|
| `start.bat` | Avvia tutto (doppio click) |
| `stop.bat` | Ferma tutto preservando i dati (doppio click) |
| `docker-compose.yml` + `docker-compose.quickstart.yml` | Configurazione dei container |
| `Dockerfile` | Ricetta per costruire l'immagine dell'applicazione |
| `docs/deployment.md` | Guida per il **deployment in produzione** (TLS, secrets reali, Redis) |
| `docs/methodology.md` | Documentazione metodologica (GHG Protocol, ESRS E1, GWP) |
| `docs/gdpr_processing_register.md` | Registro Art. 30 GDPR |
| `docs/roadmap.md` | Lavoro deferred / v2 |

---

## Domande?

Vedi `README.md` per il panorama completo, oppure i singoli documenti in
`docs/`. Il branch corrente è `claude/ghg-emissions-calculator-NFJZW`,
status: Security APPROVED + Compliance APPROVED, 540 test pass,
coverage ≥ 95% (vedi commit `f578832`).
