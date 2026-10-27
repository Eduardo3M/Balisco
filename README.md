# Balisco

Balisco es una biblioteca de escritorio para explorar y organizar archivos de Google Drive sin descargar todos los PDF. Lee los metadatos de Google Drive para escritorio y guarda tus notas y preferencias en el equipo.

## Qué permite hacer

- Explorar libros, documentos y contenedores con portadas y un panel de detalles.
- Buscar por texto, etiquetas, autor, tipo, estado y calificación. `@con:seguimiento` muestra los elementos con favoritos, calificación, estado avanzado o notas.
- Añadir notas, etiquetas, favoritos y calificaciones; editar varios elementos a la vez.
- Abrir archivos en Drive o en el Explorador de Windows.
- Recuperar la ficha de un PDF resubido con otro ID cuando hay una única coincidencia segura en la misma ruta y perfil.
- Crear una copia de seguridad de la biblioteca local y las portadas en Drive.

## Instalar en Windows x64

Ejecuta `BaliscoSetup-0.1.9-win-x64.exe`. El instalador incluye Python e instala Balisco para el usuario actual. Requiere Google Drive para escritorio y Microsoft Edge WebView2 Runtime.

Los datos personales se guardan fuera de la instalación, en `%LOCALAPPDATA%\Balisco`: `biblioteca.db`, portadas y preferencias. Los PDF permanecen en Google Drive. Actualizar o desinstalar la aplicación no elimina esa carpeta.

## Desarrollo

Requiere Windows x64 y Python 3.12 o posterior.

```powershell
python -m pip install -e ".[build]"
python Balisco.pyw
python -m unittest discover -s tests -v
```

Para crear el instalador, instala Inno Setup 6 y ejecuta `python scripts/build_installer.py`. El resultado se genera en `dist/`; para distribuirlo en GitHub, adjunta ese `.exe` a una Release.
