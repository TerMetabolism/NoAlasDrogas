# NoAlasDrogas
Usuario o Industria?

Publica cada día en TikTok los vídeos que se dejan en la carpeta `queue/`, usando la
[Content Posting API](https://developers.tiktok.com/doc/content-posting-api-reference-direct-post)
oficial desde GitHub Actions. Instagram y YouTube se añadirán más adelante.

## Limitación importante

TikTok no audita herramientas para publicar en cuentas propias
([normas](https://developers.tiktok.com/doc/content-sharing-guidelines)), así que esta app
funcionará siempre como "no auditada":

- Solo publica con privacidad **Solo yo** (`SELF_ONLY`).
- La cuenta de TikTok tiene que estar **en privado** en el momento de publicar.
- Para que un vídeo sea público hay que poner la cuenta en público y cambiar a mano la
  privacidad de ese vídeo a "Todos".

## Cómo se usa

1. Sube un vídeo a `queue/` (`.mp4`, `.mov` o `.webm`). Desde la web de GitHub el máximo es
   **25 MB por archivo**.
2. Opcional: sube junto a él un `.txt` con el mismo nombre y el texto de la publicación.
3. El workflow **Publicar en TikTok** se ejecuta dos veces al día (12:17 y 18:17 UTC) y sube
   un vídeo por ejecución, por orden alfabético. Nombra los archivos `001.mp4`, `002.mp4`…
4. Lo subido se mueve a `published/`. Si la cola está vacía, no hace nada.

Los vídeos se quedan en el historial del repositorio, que crecerá con el tiempo.

## Configuración inicial (una sola vez)

### 1. App de TikTok en modo Sandbox

En [TikTok for Developers](https://developers.tiktok.com/) crea una app y cambia el interruptor
junto a su nombre a **Sandbox** (no hace falta enviarla a revisión). Dentro del sandbox:

- Añade los productos **Login Kit** y **Content Posting API** (con *Direct Post* activado).
- Añade el permiso (*scope*) `video.publish`.
- En Login Kit, plataforma **Desktop**, registra esta URI de redirección exacta:
  `http://localhost:3455/callback/`
- En *Sandbox settings → Target users*, añade tu cuenta de TikTok.

### 2. Secretos del repositorio

En *Settings → Secrets and variables → Actions → Secrets*:

| Secreto | Valor |
|---|---|
| `TIKTOK_CLIENT_KEY` | *Client key* del sandbox |
| `TIKTOK_CLIENT_SECRET` | *Client secret* del sandbox |
| `GH_PAT` | Token de GitHub *fine-grained*, solo para este repo, con permiso de escritura de secretos |

`GH_PAT` hace falta porque TikTok cambia el token de renovación en cada uso y el workflow
tiene que guardar el nuevo en `TIKTOK_REFRESH_TOKEN`.

### 3. Autorizar el canal

1. En *Actions → Autorizar TikTok → Run workflow*, ejecuta con el campo vacío.
2. Abre la URL que aparece en el registro e inicia sesión con el canal. El navegador acabará en una
   página `localhost` que no carga: es lo esperado. Copia la URL completa de la barra de direcciones.
3. Ejecuta de nuevo el workflow pegando esa URL. Guarda `TIKTOK_REFRESH_TOKEN` y muestra el
   nombre del canal autorizado.

El token de renovación dura 180 días según TikTok; si caduca, repite este paso.

## Desarrollo

```bash
uv sync
```

```bash
uv run pytest
```
