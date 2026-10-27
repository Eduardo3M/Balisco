"""Smoke test for language property, bulk editing, bilingual/robust search, and search bar dropdown stacking."""
from contextlib import closing
from pathlib import Path
import json
import sys
import tempfile
import threading
import time

import webview

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.database import conectar, configurar
from tests.ui_smoke_fixture import DesktopAPI

RESULT = {}


def run(window):
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if window.evaluate_js('window.balisco?.state.items.length===12 && document.querySelectorAll(".card").length>=2'):
                break
            time.sleep(.05)

        script = r"""(async()=>{
          const $=id=>document.getElementById(id),S=window.balisco.state;
          const wait=async test=>{for(let i=0;i<100;i++){if(test())return;await new Promise(r=>setTimeout(r,30));}throw Error('Timed out');};

          // 1. Verify tag suggestions stacking in top toolbar position
          const tagSuggestions = $('tagSuggestions');
          const isDirectBodyChild = tagSuggestions.parentElement === document.body;
          const toolbarZIndex = window.getComputedStyle(document.querySelector('.toolbar')).zIndex;

          // 2. Test idiomas command opening modal
          const ghost = $('ghost');
          ghost.hidden = false;
          ghost.value = 'idiomas';
          await window.balisco.flush();
          // Trigger Enter on ghost
          ghost.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', bubbles: true}));
          await wait(() => $('languagesDialog').open);
          const modalOpened = $('languagesDialog').open;

          // 3. Test adding a language
          $('languageInput').value = 'Francés';
          $('languagesForm').dispatchEvent(new Event('submit', {bubbles: true, cancelable: true}));
          await wait(() => S.languages.includes('Francés'));
          const hasFrances = S.languages.includes('Francés');

          // Close modal
          $('languagesDialogClose').click();
          await wait(() => !$('languagesDialog').open);

          // 4. Test selecting an item and assigning language
          const firstId = S.items[0].drive_id;
          const cards = [...document.querySelectorAll('.card')];
          cards[0].dispatchEvent(new MouseEvent('click', {bubbles: true}));
          await wait(() => S.selected?.drive_id === firstId && !$('details').hidden);

          const itemLang = $('itemLanguage');
          const francesOptionExists = [...itemLang.options].some(o => o.value === 'Francés');
          itemLang.value = 'Español';
          itemLang.dispatchEvent(new Event('change', {bubbles: true}));
          await window.balisco.flush();

          // 5. Test bulk selection language assignment
          const secondId = S.items[1].drive_id;
          S.bulkIds = new Set([firstId, secondId]);
          itemLang.value = 'Inglés';
          itemLang.dispatchEvent(new Event('change', {bubbles: true}));
          await window.balisco.flush();

          // 6. Test delete language
          ghost.hidden = false;
          ghost.value = '@idiomas';
          ghost.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', bubbles: true}));
          await wait(() => $('languagesDialog').open);

          const delBtn = document.querySelector('[data-del-lang="Francés"]');
          if (delBtn) delBtn.click();
          await wait(() => !S.languages.includes('Francés'));
          const francesDeleted = !S.languages.includes('Francés');
          $('languagesDialogClose').click();

          // 7. Test recent search history without titles by default and with toggle command
          localStorage.removeItem('balisco.searchHistory.perfil.fixture');
          ghost.hidden = false;
          // Commit a tag, command, and title
          ghost.value = '+matematicas';
          ghost.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', bubbles: true}));
          await window.balisco.flush();

          ghost.hidden = false;
          ghost.value = '@barra';
          ghost.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', bubbles: true}));
          await window.balisco.flush();

          ghost.hidden = false;
          ghost.value = 'Calculus Stewart';
          ghost.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', bubbles: true}));
          await window.balisco.flush();

          // Focus empty search bar: by default titles must be excluded
          ghost.hidden = false;
          ghost.value = '';
          ghost.dispatchEvent(new Event('input', {bubbles: true}));
          await wait(() => !$('tagSuggestions').hidden);

          let renderedButtons = [...$('tagSuggestions').querySelectorAll('.suggestion-cmd')].map(s => s.textContent.trim());
          const hasTag = renderedButtons.includes('+matematicas');
          const hasCommand = renderedButtons.includes('@barra');
          const excludesTitleByDefault = !renderedButtons.includes('Calculus Stewart');

          // Run command to toggle titles in recents
          ghost.value = '@recientes:titulos';
          ghost.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', bubbles: true}));
          await wait(() => S.showRecentTitles === true);

          // Focus empty search bar again: now titles must be included
          ghost.hidden = false;
          ghost.value = '';
          ghost.dispatchEvent(new Event('input', {bubbles: true}));
          await wait(() => !$('tagSuggestions').hidden);

          renderedButtons = [...$('tagSuggestions').querySelectorAll('.suggestion-cmd')].map(s => s.textContent.trim());
          const includesTitleWhenEnabled = renderedButtons.includes('Calculus Stewart');

          // Toggle back to disabled
          ghost.value = '@recientes:titulos';
          ghost.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', bubbles: true}));
          await wait(() => S.showRecentTitles === false);

          // 8. Test command suggestion when typing commands
          ghost.hidden = false;
          ghost.value = '@';
          ghost.dispatchEvent(new Event('input', {bubbles: true}));
          await wait(() => !$('tagSuggestions').hidden);

          let cmdSpans = [...$('tagSuggestions').querySelectorAll('.suggestion-cmd')].map(s => s.textContent.trim());
          const hasAtIdiomas = cmdSpans.includes('@idiomas');
          const hasAtBarra = cmdSpans.includes('@barra');

          // Type specific command prefix: '@id'
          ghost.value = '@id';
          ghost.dispatchEvent(new Event('input', {bubbles: true}));
          await wait(() => [...$('tagSuggestions').querySelectorAll('.suggestion-cmd')].some(s => s.textContent.trim() === '@idiomas'));
          cmdSpans = [...$('tagSuggestions').querySelectorAll('.suggestion-cmd')].map(s => s.textContent.trim());
          const filtersAtIdiomas = cmdSpans.includes('@idiomas') && !cmdSpans.includes('@barra');

          // Type keyword without prefix: 'barra' (must NOT trigger suggestions; plain text is exclusively for titles!)
          ghost.value = 'barra';
          ghost.dispatchEvent(new Event('input', {bubbles: true}));
          await new Promise(r => setTimeout(r, 220));
          const bareKeywordHidesSuggestions = $('tagSuggestions').hidden;

          // Test section autocomplete for @estado:
          ghost.value = '@estado:';
          ghost.dispatchEvent(new Event('input', {bubbles: true}));
          await wait(() => !$('tagSuggestions').hidden && [...$('tagSuggestions').querySelectorAll('.suggestion-cmd')].some(s => s.textContent.includes('@estado:pendiente')));
          const hasStateSuggestions = [...$('tagSuggestions').querySelectorAll('.suggestion-cmd')].some(s => s.textContent.includes('@estado:pendiente'));

          // Test dynamic width of suggestions container
          const suggestionsRect = $('tagSuggestions').getBoundingClientRect();
          const hasDynamicWidth = suggestionsRect.width >= 350;

          return {
            ok: true,
            isDirectBodyChild,
            toolbarZIndex,
            modalOpened,
            hasFrances,
            francesOptionExists,
            francesDeleted,
            hasTag,
            hasCommand,
            excludesTitleByDefault,
            includesTitleWhenEnabled,
            hasAtIdiomas,
            hasAtBarra,
            filtersAtIdiomas,
            bareKeywordHidesSuggestions,
            hasStateSuggestions,
            hasDynamicWidth,
            languages: S.languages
          };
        })().catch(e=>({ok:false,error:e.message,stack:e.stack}))"""
        done = threading.Event()
        window.evaluate_js(script, callback=lambda value: (RESULT.update(value), done.set()))
        if not done.wait(10):
            RESULT.update(ok=False, error='JavaScript timeout')
        print(json.dumps(RESULT, ensure_ascii=False), flush=True)
    finally:
        window.destroy()


def main():
    with tempfile.TemporaryDirectory(prefix='balisco-lang-') as tmp:
        db_path = Path(tmp) / 'biblioteca.db'
        with closing(conectar(db_path)) as db:
            with db:
                configurar(db, 'id_perfil_drive', 'fixture')
                configurar(db, 'modo', 'local')
                for i in range(1, 13):
                    titulo = f'Book {i} Calculus Stewart' if i == 1 else f'Libro {i}'
                    etiquetas = '+diseno-personajes' if i == 1 else '+general'
                    db.execute(
                        "INSERT INTO items(drive_id,titulo,tipo,tipo_contenido,formato,tamano_bytes,ruta_relativa,perfil_drive,etiquetas) "
                        "VALUES(?,?,?,?,?,?,?,?,?)",
                        (f'd_{i}', titulo, 'pdf', 'documento', 'PDF', 1000 * i, f'Mi unidad\\b_{i}.pdf', 'fixture', etiquetas)
                    )
        api = DesktopAPI(tmp)
        window = webview.create_window('Language & Search Smoke', str(ROOT / 'ui' / 'index.html'), js_api=api, width=1000, height=700)
        webview.start(run, window, gui='edgechromium', private_mode=True)
        if not RESULT.get('ok'):
            sys.exit(1)


if __name__ == '__main__':
    main()
