# Sistema de Detección y Clasificación de Notificaciones Judiciales - ASERGES S.L.

Sistema automatizado para la detección, procesamiento, clasificación y vinculación de notificaciones judiciales recibidas por correo electrónico y desde la plataforma LexNET. El objetivo es centralizar la gestión documental, reducir el tiempo de procesamiento manual y minimizar errores, integrando los documentos directamente en el software de gestión del despacho, **Mnprogram**.

---

## 1. Arquitectura del Sistema

El sistema se compone de tres módulos principales que operan en dos entornos diferentes (un PC de oficina en Windows y un VPS en Linux) para garantizar la seguridad y la eficiencia.

```mermaid
graph TD
    subgraph "Entorno 1: VPS Linux (n8n)"
        A[Buzón de correo IONOS] -- IMAP Trigger (cada 15 min) --> B(Flujo n8n);
        B -- Filtra por procuradores --> C{¿Email de procurador?};
        C -- Sí --> D{¿Tiene PDF?};
        D -- Sí --> E[Reenvía PDF al Worker];
        D -- No --> F[Notifica por email: Sin adjuntos];
        E -- POST /procesar --> G((PC Windows));
        C -- No --> H[Ignora];
    end

    subgraph "Entorno 2: PC Windows (Oficina)"
        G -- Recibe PDF --> I[Worker Python (Flask)];
        I -- OCR y Regex --> J[Extrae Metadatos];
        J -- Búsqueda por prioridad --> K{¿Encuentra Expediente?};
        K -- Sí --> L[Guarda PDF en carpeta del expediente];
        K -- No --> M[Guarda PDF en carpeta '_Pendientes'];
        L --> N[Responde OK a n8n];
        M --> N;

        P[Tarea Programada Windows] -- Ejecuta cada 30 min --> Q(Scraper LexNET);
        Q -- Accede con certificado --> R[Plataforma LexNET];
        R -- Descarga PDFs no leídos --> S[Envía PDFs al Worker];
        S -- POST /procesar --> I;
    end

    subgraph "Base de Datos (Local)"
        I -- pyodbc / API SOAP --> O[SQL Server (Mnprogram)];
    end

    subgraph "Alertas y Notificaciones"
        B -- En caso de error --> T[Email de Alerta];
        E -- Si el Worker falla --> T;
        K -- Si no encuentra expediente --> U[Email de Alerta URGENTE];
        K -- Si encuentra expediente --> V[Email de Confirmación OK];
    end
```

| Componente | Entorno | Tecnología | Responsabilidad |
| :--- | :--- | :--- | :--- |
| **Flujo n8n** | VPS Linux | n8n (self-hosted) | Monitorear el buzón de correo, filtrar emails de procuradores y reenviar los PDFs al worker. | 
| **Worker Python** | PC Windows | Flask, pyodbc, pdfplumber, pytesseract | Recibir PDFs, extraer metadatos (NIG, procedimiento, etc.) mediante OCR y regex, buscar el expediente en Mnprogram (SQL Server) y guardar el archivo en la carpeta correspondiente. | 
| **Scraper LexNET** | PC Windows | Playwright, Tarea Programada | Acceder a LexNET con el certificado digital instalado en Chrome, descargar notificaciones no leídas y enviarlas al worker para su procesamiento. |
| **Base de Datos** | PC Windows (Local) | SQL Server | Almacena los datos de los expedientes jurídicos del despacho (Mnprogram). |

---

## 2. Características Principales

- **Doble Vía de Entrada**: Procesamiento automático tanto de correos de procuradores como de notificaciones de LexNET.
- **Extracción Inteligente de Datos**: Uso combinado de **OCR (Tesseract)** y **expresiones regulares (regex)** para extraer con alta precisión datos clave como el NIG, número de procedimiento, tipo de resolución y partes implicadas.
- **Vinculación con Expedientes**: Búsqueda priorizada en la base de datos de **Mnprogram** para asociar cada documento a su expediente correcto.
- **Clasificación Automática**: Los documentos se archivan en una estructura de carpetas organizada (`Año/Mes/`) si se encuentra el expediente, o en una carpeta de `_Pendientes` para revisión manual.
- **Prevención de Duplicados**: Sistema de **deduplicación basado en hash SHA-256** para evitar procesar el mismo documento dos veces.
- **Tolerancia a Fallos**: El sistema está diseñado para ser robusto. Si un componente falla (ej. cambio en la web de LexNET), los otros siguen operativos.
- **Seguridad**: Los documentos sensibles se procesan localmente en el PC de la oficina, sin utilizar servicios en la nube de terceros, garantizando la confidencialidad y el secreto profesional.
- **Alertas y Monitorización**: Flujo de notificaciones por email para informar sobre el estado del procesamiento (éxito, pendiente de clasificación, error).

---

## 3. Prerrequisitos

Antes de la instalación, asegúrese de cumplir con los siguientes requisitos en los entornos correspondientes.

#### En el PC de Oficina (Windows)

1.  **Windows 10/11** o Windows Server.
2.  **Python 3.11 o superior**: Descargar desde [python.org](https://www.python.org/). Durante la instalación, marque la casilla `Add Python to PATH`.
3.  **Tesseract OCR**: Descargar e instalar desde [UB Mannheim](https://github.com/UB-Mannheim/tesseract/wiki). Anote la ruta de instalación (ej. `C:\Program Files\Tesseract-OCR`).
4.  **Google Chrome**: Instalado con el **certificado digital de LexNET** configurado y funcionando correctamente en un perfil específico (normalmente el perfil `Default`).
5.  **Acceso de Red**: El PC debe tener acceso a la base de datos de Mnprogram (SQL Server) y una IP fija o nombre de host accesible desde el VPS donde se ejecuta n8n.
6.  **Permisos de Administrador**: Necesarios para instalar el servicio de Windows y la tarea programada.

#### En el VPS (Linux)

1.  **n8n (self-hosted)**: Una instancia de n8n instalada y en funcionamiento. Se recomienda usar Docker para una gestión más sencilla.
2.  **Credenciales de Correo**: Acceso IMAP/SMTP al buzón de correo de IONOS que se va a monitorear.

---

## 4. Instalación y Configuración

Siga estos pasos para desplegar el sistema completo.

### Paso 1: Clonar y Configurar el Repositorio (PC Windows)

1.  **Descargue o clone este repositorio** en una carpeta del PC de la oficina. Por ejemplo: `C:\Users\ASERGES\Documents\judicial-doc-system`.

2.  **Cree el archivo `.env`**: En la raíz del proyecto, haga una copia de `.env.example` y renómbrela a `.env`.

3.  **Edite el archivo `.env`** con un editor de texto y rellene todas las variables según su configuración. Preste especial atención a:
    -   `ESCANER_BASE`: La ruta donde se guardarán los documentos.
    -   `TESSERACT_CMD`: La ruta donde instaló Tesseract.
    -   `SQL_SERVER`, `SQL_DATABASE`, `SQL_USER`, `SQL_PASSWORD`: Los datos de conexión a su base de datos Mnprogram.
    -   `CHROME_USER_DATA_DIR` y `CHROME_PROFILE`: Generalmente no necesitan cambios si usa el perfil principal de Chrome.

### Paso 2: Instalar el Worker como Servicio (PC Windows)

1.  Haga clic derecho sobre el archivo `instalar_worker.bat` y seleccione **"Ejecutar como administrador"**.
2.  El script realizará automáticamente los siguientes pasos:
    -   Creará un entorno virtual de Python en la carpeta `venv`.
    -   Instalará todas las dependencias necesarias (Flask, pyodbc, etc.).
    -   Descargará **NSSM (Non-Sucking Service Manager)** para gestionar el servicio.
    -   Creará un servicio de Windows llamado `JudicialWorkerASERGESSL` que se iniciará automáticamente con el sistema.
3.  Una vez finalizado, el worker estará en ejecución y escuchando en el puerto especificado (por defecto, `8765`).

> **Firewall de Windows**: Asegúrese de que el firewall de Windows permite las conexiones entrantes en el puerto `8765` para que el servidor n8n pueda comunicarse con el worker.

### Paso 3: Programar el Scraper de LexNET (PC Windows)

1.  Haga clic derecho sobre el archivo `lexnet_scheduler.bat` y seleccione **"Ejecutar como administrador"**.
2.  El script creará una nueva tarea en el **Programador de Tareas de Windows** llamada `ScraperLexNET_ASERGES`.
3.  Esta tarea ejecutará el script `lexnet_scraper.py` **cada 30 minutos**, siempre que el usuario haya iniciado sesión.

> **Importante**: Para que el scraper funcione, **Google Chrome debe estar completamente cerrado** antes de cada ejecución. La tarea se encarga de abrirlo y cerrarlo.

### Paso 4: Configurar el Flujo en n8n (VPS Linux)

1.  **Acceda a su interfaz de n8n**.
2.  Vaya a `Workflows` y haga clic en `Import from File`.
3.  Seleccione el archivo `n8n_flow.json` de este repositorio.
4.  Una vez importado, deberá configurar los nodos que tienen notas de "CONFIGURAR":
    -   **Nodo `IMAP - Buzón IONOS`**: En la sección `Credentials`, cree unas nuevas credenciales IMAP con los datos de su buzón de IONOS.
    -   **Nodo `Filtro Lista Blanca Procuradores`**: Edite las condiciones para incluir las direcciones de correo o dominios de los procuradores autorizados.
    -   **Nodo `Enviar PDF al Worker`**: Modifique la URL para que apunte a la **IP pública o dominio del VPS y el puerto mapeado al PC de la oficina**, o la **IP local del PC de Windows** si n8n está en la misma red. Ejemplo: `http://192.168.1.50:8765/procesar`.
    -   **Nodos de Email (`Email Confirmación OK`, `Email Alerta URGENTE`, etc.)**: En la sección `Credentials`, cree unas nuevas credenciales SMTP con los datos de su cuenta de correo de IONOS.
5.  **Active el flujo** (usando el toggle en la parte superior derecha).

¡El sistema ya está operativo!

---

## 5. Descripción de los Ficheros

-   `judicial_worker.py`: El corazón del sistema. Un microservicio Flask que recibe los PDFs y realiza toda la lógica de procesamiento.
-   `lexnet_scraper.py`: Script de automatización con Playwright que simula la interacción humana para descargar notificaciones de LexNET.
-   `n8n_flow.json`: Definición del flujo de trabajo de n8n en formato JSON, listo para ser importado.
-   `instalar_worker.bat`: Script de instalación para Windows que configura el entorno de Python y crea el servicio del worker.
-   `lexnet_scheduler.bat`: Script que crea la tarea programada en Windows para ejecutar el scraper de LexNET periódicamente.
-   `.env.example`: Plantilla con todas las variables de entorno necesarias para la configuración. Se debe copiar a `.env`.
-   `requirements.txt`: (Generado por el script de instalación) Lista de las librerías de Python necesarias para el proyecto.
-   `README.md`: Este mismo documento.

---

## 6. Troubleshooting (Solución de Problemas)

-   **El worker no se inicia**: Verifique que Python 3.11+ está en el PATH. Ejecute `instalar_worker.bat` como administrador. Revise el log `judicial_worker.log` para ver mensajes de error.
-   **El scraper de LexNET no funciona**: Asegúrese de que Chrome está cerrado antes de la ejecución. Verifique que el certificado digital funciona manualmente. Revise el log `lexnet_scraper.log`.
-   **n8n no puede conectar con el worker**: Compruebe la configuración del firewall en el PC de Windows. Asegúrese de que la IP y el puerto en el nodo `Enviar PDF al Worker` de n8n son correctos y accesibles desde el servidor n8n.
-   **El OCR no extrae bien los datos**: La calidad del escaneo del documento original es crucial. El sistema intenta usar `pdfplumber` primero y recurre a OCR si el texto no es legible. Documentos de muy baja calidad pueden seguir requiriendo revisión manual.

---

*Este sistema ha sido desarrollado por **Asesores y Abogados ASerges SL** para la automatización de sus procesos internos.*
