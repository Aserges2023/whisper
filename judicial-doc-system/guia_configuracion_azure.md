# Guía de Configuración: Microsoft Graph API para OneDrive

Para que el pipeline judicial pueda subir archivos a OneDrive de forma totalmente automática y en segundo plano (sin pedir contraseñas ni SMS), es necesario registrar una aplicación en Microsoft Entra ID (antes Azure AD).

Sigue estos pasos con una cuenta de **Administrador Global** de Microsoft 365.

## Paso 1: Registrar la aplicación

1. Entra en el [Portal de Microsoft Entra](https://entra.microsoft.com/) e inicia sesión.
2. En el menú izquierdo, ve a **Identity > Applications > App registrations** (Registros de aplicaciones).
3. Haz clic en **New registration** (Nuevo registro).
4. Nombre: `Pipeline Judicial Aserges` (o similar).
5. Tipos de cuenta compatibles: Selecciona **Accounts in this organizational directory only** (Solo cuentas de este directorio organizativo).
6. Haz clic en **Register** (Registrar).

## Paso 2: Obtener los IDs necesarios

Una vez registrada, verás la página de información general (Overview) de la aplicación.
Copia y guarda estos dos valores, los necesitarás para el archivo `.env.judicial`:

* **Application (client) ID** -> Esto será `AZURE_CLIENT_ID`
* **Directory (tenant) ID** -> Esto será `AZURE_TENANT_ID`

## Paso 3: Configurar permisos de la API

1. En el menú izquierdo de la aplicación, ve a **API permissions** (Permisos de API).
2. Haz clic en **Add a permission** (Agregar un permiso).
3. Selecciona **Microsoft Graph**.
4. Selecciona **Application permissions** (Permisos de la aplicación) — *¡Muy importante! No elijas Delegated.*
5. En el buscador, escribe `Files` y marca la casilla **Files.ReadWrite.All**.
6. En el buscador, escribe `Sites` y marca la casilla **Sites.ReadWrite.All**.
7. Haz clic en **Add permissions** (Agregar permisos).

## Paso 4: Conceder consentimiento de administrador

1. En la misma pantalla de permisos, verás que los permisos añadidos tienen un triángulo naranja que dice "Not granted for...".
2. Haz clic en el botón **Grant admin consent for [Nombre de tu empresa]** (Conceder consentimiento de administrador para...).
3. Confirma haciendo clic en **Yes**. Los triángulos naranjas cambiarán a checks verdes.

## Paso 5: Crear un secreto de cliente (Contraseña de la app)

1. En el menú izquierdo, ve a **Certificates & secrets** (Certificados y secretos).
2. Ve a la pestaña **Client secrets** (Secretos de cliente) y haz clic en **New client secret** (Nuevo secreto de cliente).
3. Descripción: `Clave Pipeline`.
4. Expira: Selecciona **24 months** (24 meses).
5. Haz clic en **Add** (Agregar).
6. **¡IMPORTANTE!** Copia inmediatamente el valor de la columna **Value** (Valor). No podrás volver a verlo después de salir de esta pantalla.
   * Este valor será `AZURE_CLIENT_SECRET` en el archivo `.env.judicial`.

## Paso 6: Configurar el archivo .env.judicial

Abre el archivo `~/.env.judicial` en el servidor y rellena los valores obtenidos:

```env
AZURE_TENANT_ID=tu_tenant_id_aqui
AZURE_CLIENT_ID=tu_client_id_aqui
AZURE_CLIENT_SECRET=tu_client_secret_aqui
```

Una vez configurado, el pipeline `pipeline_judicial_v3.py` podrá subir archivos a OneDrive automáticamente.
