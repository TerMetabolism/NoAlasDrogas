# NoAlasDrogas
Usuario o Industria?

Publica cada día en TikTok los vídeos que se dejan en la carpeta `queue/`, usando la
[Content Posting API](https://developers.tiktok.com/doc/content-posting-api-reference-direct-post)
oficial desde GitHub Actions. Instagram y YouTube se añadirán más adelante.

## Cómo se usa

1. Sube un vídeo a `queue/` (`.mp4`, `.mov` o `.webm`, máximo 100 MB por el límite de GitHub).
2. Opcional: sube junto a él un `.txt` con el mismo nombre y el texto de la publicación.
3. El workflow **Publicar en TikTok** se ejecuta dos veces al día (12:17 y 18:17 UTC) y publica
   un vídeo por ejecución, por orden alfabético. Nombra los archivos `001.mp4`, `002.mp4`…
4. Lo publicado se mueve a `published/`. Si la cola está vacía, no hace nada.

## Configuración inicial (una sola vez)

### 1. App de TikTok

En [TikTok for Developers](https://developers.tiktok.com/) crea una app y:

- Añade los productos **Login Kit** y **Content Posting API** (con *Direct Post* activado).
- Pide el permiso (*scope*) `video.publish`.
- En Login Kit, plataforma **Desktop**, registra esta URI de redirección exacta:
  `http://localhost:3455/callback/`

Hasta que TikTok apruebe la auditoría de la app, solo se puede publicar en una cuenta
**privada** y todo queda visible solo para ti.

### 2. Secretos del repositorio

En *Settings → Secrets and variables → Actions → Secrets*:

| Secreto | Valor |
|---|---|
| `TIKTOK_CLIENT_KEY` | *Client key* de la app de TikTok |
| `TIKTOK_CLIENT_SECRET` | *Client secret* de la app de TikTok |
| `GH_PAT` | Token de GitHub *fine-grained*, solo para este repo, con permiso **Secrets: Read and write** |

`GH_PAT` hace falta porque TikTok cambia el token de renovación en cada uso y el workflow
tiene que guardar el nuevo en `TIKTOK_REFRESH_TOKEN`.

### 3. Autorizar el canal

1. En *Actions → Autorizar TikTok → Run workflow*, ejecuta con el campo vacío.
2. Abre la URL que aparece en el registro e inicia sesión con el canal. El navegador acabará en una
   página `localhost` que no carga: es lo esperado. Copia la URL completa de la barra de direcciones.
3. Ejecuta de nuevo el workflow pegando esa URL. Guarda `TIKTOK_REFRESH_TOKEN` y muestra el
   nombre del canal autorizado.

La autorización caduca si pasan 180 días sin ninguna publicación; entonces hay que repetir este paso.

### 4. Privacidad

Por defecto se publica como `SELF_ONLY` (solo yo). Cuando TikTok apruebe la auditoría, crea la
variable `TIKTOK_PRIVACY` con valor `PUBLIC_TO_EVERYONE` en
*Settings → Secrets and variables → Actions → Variables*.

## Desarrollo

```bash
uv sync
```

```bash
uv run pytest
```
