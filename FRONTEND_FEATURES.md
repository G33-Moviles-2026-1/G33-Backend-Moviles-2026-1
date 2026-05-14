# Frontend Implementation Guide: Nuevas Funcionalidades (Mayo 2026)

Guía completa para implementar las nuevas características en la aplicación móvil: notificaciones in-app, cambio de contraseña, cambio de email con cooldown, y modo "no molestar" (incognito).

---

## Tabla de contenidos

1. [Notificaciones In-App](#1-notificaciones-in-app)
2. [Cambio de Contraseña](#2-cambio-de-contraseña)
3. [Cambio de Email con Cooldown](#3-cambio-de-email-con-cooldown)
4. [Status/Modo "No Molestar" (Incognito)](#4-statusmodo-no-molestar-incognito)
5. [Manejo de Errores](#5-manejo-de-errores)
6. [Recomendaciones de UX/UI](#6-recomendaciones-de-uxui)

---

## 1) Notificaciones In-App

### Descripción

Cuando un amigo crea una reserva de sala, el usuario recibe una notificación in-app (si no está en estado `incognito`). Las notificaciones se guardan en la base de datos y el usuario puede marcarlas como leídas.

### Endpoints

#### GET `/notifications/`

Obtiene las últimas 50 notificaciones del usuario autenticado.

**Request:**
```http
GET /notifications/
Authorization: Cookie(session=...)
```

**Response (200 OK):**
```json
{
  "total": 5,
  "unread": 2,
  "items": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440001",
      "type": "friend_booking",
      "payload": {
        "friend_username": "Juan",
        "room_id": "ML 517",
        "date": "2026-05-15",
        "start_time": "10:30:00",
        "end_time": "12:00:00"
      },
      "is_read": false,
      "created_at": "2026-05-13T14:30:00+00:00"
    },
    {
      "id": "550e8400-e29b-41d4-a716-446655440002",
      "type": "friend_booking",
      "payload": {
        "friend_username": "Maria",
        "room_id": "LL 105",
        "date": "2026-05-14",
        "start_time": "08:00:00",
        "end_time": "09:30:00"
      },
      "is_read": true,
      "created_at": "2026-05-13T10:15:00+00:00"
    }
  ]
}
```

#### PUT `/notifications/read-all`

Marca todas las notificaciones del usuario como leídas.

**Request:**
```http
PUT /notifications/read-all
Authorization: Cookie(session=...)
```

**Response (200 OK):**
```json
{
  "message": "All notifications marked as read",
  "notifications_updated": 2
}
```

#### PUT `/notifications/{notification_id}/read`

Marca una notificación específica como leída.

**Request:**
```http
PUT /notifications/550e8400-e29b-41d4-a716-446655440001/read
Authorization: Cookie(session=...)
```

**Response (200 OK):**
```json
{
  "message": "Notification marked as read",
  "notification_id": "550e8400-e29b-41d4-a716-446655440001"
}
```

**Response (404 Not Found):**
```json
{
  "detail": "Notification not found or does not belong to this user"
}
```

### Implementación recomendada

#### 1. Crear un repositorio/service para notificaciones

```kotlin
// NotificationsService.kt
interface NotificationsService {
    suspend fun getNotifications(): NotificationsResponse
    suspend fun markAllAsRead(): Result<Unit>
    suspend fun markAsRead(notificationId: String): Result<Unit>
}

data class NotificationsResponse(
    val total: Int,
    val unread: Int,
    val items: List<Notification>
)

data class Notification(
    val id: String,
    val type: String,  // "friend_booking"
    val payload: BookingNotificationPayload,
    val isRead: Boolean,
    val createdAt: String
)

data class BookingNotificationPayload(
    val friendUsername: String,
    val roomId: String,
    val date: String,
    val startTime: String,
    val endTime: String
)
```

#### 2. Pantalla de notificaciones

**Ubicación recomendada:** Tab o ícono en la barra de navegación inferior.

**Componentes:**
- **Contador de no leídas:** Mostrar un badge con el número de notificaciones sin leer (rojo o con color destacado)
- **Lista de notificaciones:** Usar un `LazyColumn` o similar para la lista
  - Mostrar como tarjetas con los detalles de la reserva del amigo
  - Indicador visual para diferenciar leídas de no leídas (opacidad, color diferente, etc.)
  - Fecha/hora relativa (ej: "hace 2 horas")
  
- **Acción al tocar una notificación:** 
  - Abrir los detalles de la reserva/sala
  - Marcar como leída
  
- **Botón "Marcar todo como leído":** En el header de la pantalla, con un ícono de check o similar

**Estructura sugerida de tarjeta de notificación:**
```
┌─────────────────────────────────┐
│  🔔 Juan reservó ML 517        │  ← Ícono + amigo + sala
│     2026-05-15 10:30 - 12:00   │  ← Fecha y hora
│                                  │
│  [Marcar como leído] [Ver sala]│  ← Acciones (opcional)
└─────────────────────────────────┘
```

#### 3. Polling automático

Implementa un mecanismo para actualizar notificaciones periódicamente:

```kotlin
// Llamar cada 30-60 segundos mientras la app está en foreground
LaunchedEffect(Unit) {
    while (isActive) {
        notificationsViewModel.refreshNotifications()
        delay(30000)  // 30 segundos
    }
}
```

#### 4. Indicadores visuales

- **Badge en el ícono de notificaciones:** Mostrar el conteo de no leídas
- **Distinción visual:** Las notificaciones leídas pueden tener opacidad reducida o un fondo gris
- **Animación al llegar notificación:** Toast/Snackbar opcional informando que llegó una nueva notificación

---

## 2) Cambio de Contraseña

### Descripción

Permite al usuario cambiar su contraseña. La contraseña actual es requerida por seguridad.

### Endpoint

#### PUT `/me/password`

**Request:**
```http
PUT /me/password
Authorization: Cookie(session=...)
Content-Type: application/json

{
  "current_password": "mi_password_actual",
  "new_password": "mi_nuevo_password"
}
```

**Response (200 OK):**
```json
{
  "message": "Password updated successfully"
}
```

**Response (400 Bad Request):**
```json
{
  "detail": "Current password is incorrect"
}
```

### Implementación recomendada

#### 1. Crear un servicio para cambio de contraseña

```kotlin
// AuthService.kt
interface AuthService {
    suspend fun changePassword(
        currentPassword: String,
        newPassword: String
    ): Result<Unit>
}
```

#### 2. Pantalla de cambio de contraseña

**Ubicación recomendada:** Settings → Account → Change Password

**Componentes:**
- **Campo de contraseña actual:** 
  - Máscara por defecto (`*` o viñetas)
  - Botón para mostrar/ocultar
  
- **Campo de nueva contraseña:**
  - Máscara por defecto
  - Validación en tiempo real:
    - Mínimo 8 caracteres (recomendado)
    - Mostrar fortaleza (débil, media, fuerte)
    - Indicador visual (barra de color)
  
- **Campo de confirmar nueva contraseña:**
  - Verificar que coinciden antes de enviar
  
- **Botón "Cambiar":**
  - Deshabilitado hasta que los campos sean válidos
  - Mostrar loading mientras se procesa
  - Éxito: mostrar SnackBar "Contraseña actualizada" y volver atrás

**Validaciones del cliente:**
```kotlin
fun isPasswordValid(password: String): Boolean {
    // Mínimo 8 caracteres
    return password.length >= 8
}

fun passwordsMatch(password1: String, password2: String): Boolean {
    return password1 == password2
}
```

**Manejo de errores:**
- Contraseña actual incorrecta → Mostrar error debajo del campo
- Error de red → Mostrar SnackBar con opción de reintentar
- Otra error → Mostrar diálogo genérico de error

---

## 3) Cambio de Email con Cooldown

### Descripción

Permite al usuario cambiar su email. Debe ser un email de Uniandes (`@uniandes.edu.co`). Existe un cooldown de 30 días entre cambios.

### Endpoint

#### PUT `/me/email`

**Request:**
```http
PUT /me/email
Authorization: Cookie(session=...)
Content-Type: application/json

{
  "new_email": "juan.david.roa.moyano@uniandes.edu.co",
  "current_password": "mi_password"
}
```

**Response (200 OK):**
```json
{
  "email": "juan.david.roa.moyano@uniandes.edu.co",
  "message": "Email updated successfully"
}
```

**Response (400 Bad Request):**
```json
{
  "detail": "Email must end with @uniandes.edu.co"
}
```

**Response (400 Bad Request - Email en uso):**
```json
{
  "detail": "Email is already in use"
}
```

**Response (429 Too Many Requests - Cooldown):**
```json
{
  "detail": "Email can only be changed once every 30 days",
  "days_left": 24
}
```

### Implementación recomendada

#### 1. Crear un servicio para cambio de email

```kotlin
// UserService.kt
interface UserService {
    suspend fun changeEmail(
        newEmail: String,
        currentPassword: String
    ): Result<Unit>
}

data class EmailChangeError(
    val message: String,
    val daysLeft: Int? = null  // Solo cuando es error de cooldown
)
```

#### 2. Pantalla de cambio de email

**Ubicación recomendada:** Settings → Account → Change Email

**Componentes:**
- **Email actual (solo lectura):** Mostrar el email actual en gris
  
- **Campo de nuevo email:**
  - Validación en tiempo real:
    - Debe terminar en `@uniandes.edu.co`
    - Mostrar error si no es válido
  - Autocompletar con `@uniandes.edu.co` si el usuario solo escribe la parte antes del `@`
  
- **Campo de contraseña:**
  - Requerido por seguridad
  
- **Información de cooldown:**
  - Si el usuario ya cambió email hace poco, mostrar un texto informativo:
    ```
    ℹ️ Podrás cambiar tu email el DD de MMMM
    Faltan X días
    ```
  - Desabilitar el botón de cambiar si está en cooldown
  
- **Botón "Cambiar email":**
  - Deshabilitado si los campos no son válidos o está en cooldown
  - Mostrar loading mientras se procesa

**Flujo cuando está en cooldown:**
1. Cargar la pantalla → Detectar que está en cooldown
2. Mostrar mensaje informativo con fecha de próximo cambio
3. Desabilitar los campos de entrada
4. Desabilitar el botón (grisado)

**Validaciones del cliente:**
```kotlin
fun isValidUniandesEmail(email: String): Boolean {
    return email.trim().toLowerCase().endsWith("@uniandes.edu.co")
}

fun formatUniandesEmail(input: String): String {
    val cleaned = input.trim().toLowerCase()
    return if (cleaned.contains("@")) {
        cleaned
    } else {
        "$cleaned@uniandes.edu.co"
    }
}
```

**Manejo de errores:**
- Email inválido → Mostrar error bajo el campo
- Email en uso → Mostrar diálogo: "Este email ya está registrado"
- En cooldown → Mostrar el contador de días restantes y deshabilitar
- Contraseña incorrecta → Mostrar error bajo el campo de contraseña
- Error de red → Mostrar SnackBar con opción de reintentar

---

## 4) Status/Modo "No Molestar" (Incognito)

### Descripción

El usuario puede cambiar su estado a `incognito` (no molestar) para no recibir notificaciones de reservas de amigos. Este status puede estar combinado con otros (online, offline, busy, etc.) o ser independiente.

### Endpoint

#### PUT `/me/status`

**Request:**
```http
PUT /me/status
Authorization: Cookie(session=...)
Content-Type: application/json

{
  "status": "incognito"
}
```

Valores posibles: `online`, `offline`, `busy`, `incognito`

**Response (200 OK):**
```json
{
  "status": "incognito",
  "message": "Status updated successfully"
}
```

### Implementación recomendada

#### 1. Servicio para cambiar status

```kotlin
// UserService.kt
enum class UserStatus {
    ONLINE,
    OFFLINE,
    BUSY,
    INCOGNITO
}

interface UserService {
    suspend fun changeStatus(status: UserStatus): Result<Unit>
    suspend fun getCurrentStatus(): Result<UserStatus>
}
```

#### 2. Componente de status en la UI principal

**Ubicación recomendada:** 
- Perfil del usuario (header)
- Settings → Status
- Un botón/toggle quick-access en la pantalla principal

**Opciones de diseño:**

**Opción A - Toggle rápido en Settings:**
```
Settings
├── Account
│   ├── Change Password
│   ├── Change Email
│   └── Status
│       └── [Toggle] Modo "No molestar" (incognito)
│           Desactiva notificaciones de reservas de amigos
```

**Opción B - Selector de status en el perfil:**
```
┌──────────────────────────────┐
│  Juan Doe                    │  ← Nombre
│                              │
│  Status: [Online ▼]          │  ← Dropdown
│    • Online                  │
│    • Offline                 │
│    • Ocupado (Busy)          │
│    • No molestar (Incognito) │  ← Con descripción
└──────────────────────────────┘
```

**Opción C - Indicador con ícono:**
En el perfil, mostrar un ícono que represente el estado:
- 🟢 Online
- ⚪ Offline
- 🔴 Busy/Ocupado
- 🔕 Incognito/No molestar

Al tocar el ícono → Abre menú para cambiar

#### 3. Indicador visual de "No molestar"

Cuando el usuario está en modo `incognito`:
- Mostrar un ícono o badge distintivo en su perfil
- En la pantalla de amigos, mostrar que está en "No molestar"
- Opcionalmente, mostrar un banner en el home informando al usuario que no está recibiendo notificaciones

**Banner sugerido:**
```
┌────────────────────────────────┐
│ 🔕 Estás en modo "No molestar" │
│ No recibirás notificaciones     │
│ de reservas de amigos          │
│                                │
│  [Desactivar] [Entendido]      │
└────────────────────────────────┘
```

#### 4. Sincronización del status

Cargar el status actual cuando la app inicia:

```kotlin
// En ViewModel o MainActivity
LaunchedEffect(Unit) {
    userService.getCurrentStatus().onSuccess { status ->
        viewModel.updateUserStatus(status)
    }
}
```

---

## 5) Manejo de Errores

### Errores comunes y cómo manejarlos

| Error | Status | Causa probable | Acción recomendada |
|-------|--------|-----------------|-------------------|
| "No active session" | 401 | Sesión expirada | Redirigir a login |
| "Current password is incorrect" | 400 | Password inválida | Mostrar error en campo, permitir reintentar |
| "Email must end with @uniandes.edu.co" | 400 | Email inválido | Mostrar error bajo el campo |
| "Email is already in use" | 400 | Email duplicado | Mostrar diálogo informativo |
| "Email can only be changed once every 30 days" | 429 | En cooldown | Mostrar días restantes, deshabilitar campo |
| "Notification not found" | 404 | Notificación no existe | Actualizar la lista (refrescar) |
| Error de red | - | Sin conexión | Mostrar SnackBar con opción de reintentar |

### Implementación de manejo de errores

```kotlin
// ErrorHandler.kt
sealed class ApiError {
    data class ValidationError(val message: String) : ApiError()
    data class UnauthorizedError(val message: String) : ApiError()
    data class CooldownError(val daysLeft: Int, val message: String) : ApiError()
    data class NotFoundError(val message: String) : ApiError()
    data class NetworkError(val exception: Exception) : ApiError()
    data class ServerError(val statusCode: Int, val message: String) : ApiError()
}

// Usar en la UI
when (val error = result.exceptionOrNull() as? ApiError) {
    is ApiError.ValidationError -> showErrorSnackbar(error.message)
    is ApiError.CooldownError -> showCooldownDialog(error.daysLeft)
    is ApiError.UnauthorizedError -> navigateToLogin()
    is ApiError.NetworkError -> showNetworkErrorSnackbar()
    else -> showGenericErrorDialog(error?.message ?: "Unknown error")
}
```

---

## 6) Recomendaciones de UX/UI

### Navegación

**Estructura sugerida para Settings:**
```
Settings / Configuración
├── Account / Cuenta
│   ├── Profile / Perfil
│   ├── Status / Estado
│   ├── Change Password / Cambiar Contraseña
│   └── Change Email / Cambiar Correo
├── Notifications / Notificaciones
│   ├── Enable notifications / Habilitar notificaciones
│   └── Sound & Vibration / Sonido y vibración
├── Privacy / Privacidad
└── About / Acerca de
```

### Estilo y consistencia

Para mantener el estilo existente de la app, considera:

1. **Colores:**
   - Usar los colores primarios y secundarios ya definidos
   - Para estados de error: rojo/naranja
   - Para éxito: verde
   - Para cooldown/información: azul/gris

2. **Tipografía:**
   - Mantener la misma familia de fuentes
   - Usar tamaños consistentes (Headlines, Body, Caption, etc.)

3. **Espaciado:**
   - Mantener el padding y margin usado en otras pantallas
   - Usar el mismo grid/spacing system

4. **Componentes:**
   - TextFields: Igual estilo que en login/registro
   - Buttons: Mismo estilo que en otras pantallas
   - Cards: Si hay tarjetas en otras partes, usar el mismo diseño
   - Diálogos: Mantener consistencia con diálogos existentes

5. **Animaciones:**
   - Transiciones suaves entre pantallas
   - Loading spinners con el mismo estilo
   - Animaciones de entrada para nuevas vistas

### Patrones de UI recomendados

**Para formularios (Password, Email):**
```
┌─────────────────────────┐
│ Cambiar Contraseña      │  ← Header
├─────────────────────────┤
│                         │
│ Contraseña Actual       │
│ ┌─────────────────────┐ │
│ │ ●●●●●●●●●●●●   👁  │ │
│ └─────────────────────┘ │
│ ⓘ Mínimo 8 caracteres   │  ← Helper text
│                         │
│ Nueva Contraseña        │
│ ┌─────────────────────┐ │
│ │ ●●●●●●●●●●   👁    │ │
│ └─────────────────────┘ │
│ ▓▓░░░░░░░░ Débil       │  ← Strength indicator
│                         │
│ Confirmar Contraseña    │
│ ┌─────────────────────┐ │
│ │ ●●●●●●●●●●   👁    │ │
│ └─────────────────────┘ │
│                         │
│  [Cancelar] [Cambiar]   │  ← Botones
└─────────────────────────┘
```

**Para notificaciones (lista):**
```
┌──────────────────────┐
│ Notificaciones   ⚙️   │  ← Header con botón de "marcar todo"
├──────────────────────┤
│                      │
│ 🔔 Juan reservó     │
│    ML 517           │
│    2026-05-15       │
│    10:30 - 12:00    │
│ ✓ Marcar como leído │
│                      │
├──────────────────────┤
│ 🔔 Maria reservó    │
│    LL 105           │
│    2026-05-14       │
│    08:00 - 09:30    │
│                      │
└──────────────────────┘
```

### Flujos de usuario principales

**Flujo 1: Cambio de contraseña**
```
Settings
  ↓
Account → Change Password
  ↓
Ingresa contraseña actual
  ↓
Ingresa nueva contraseña (validación en tiempo real)
  ↓
Confirma nueva contraseña
  ↓
Presiona "Cambiar"
  ↓
Loading...
  ↓
✅ Éxito → SnackBar → Volver atrás
❌ Error → Mostrar error → Permitir reintentar
```

**Flujo 2: Cambio de email**
```
Settings
  ↓
Account → Change Email
  ↓
Ver email actual (read-only)
  ↓
Ingresa nuevo email
  ↓
Valida dominio @uniandes.edu.co
  ↓
Ingresa contraseña (verificación de seguridad)
  ↓
Presiona "Cambiar email"
  ↓
Loading...
  ↓
✅ Éxito → SnackBar → Volver atrás
❌ Cooldown → Mostrar días restantes → Deshabilitar campos
❌ Error → Mostrar error → Permitir reintentar
```

**Flujo 3: Ver notificaciones**
```
Pantalla Principal
  ↓
Toca ícono de notificaciones (o tab)
  ↓
GET /notifications/
  ↓
Mostrar lista de notificaciones
  ↓
Usuario toca notificación
  ↓
Marca como leída (PUT /notifications/{id}/read)
  ↓
Abre detalles de la sala/reserva
```

---

## Checklist de Implementación

### Notificaciones
- [ ] Crear NotificationsService con métodos para obtener, marcar como leído
- [ ] Crear pantalla de notificaciones con lista
- [ ] Mostrar badge con contador de no leídas
- [ ] Implementar polling automático (cada 30-60 segundos)
- [ ] Diferenciar notificaciones leídas vs no leídas visualmente
- [ ] Implementar botón "Marcar todo como leído"
- [ ] Manejo de errores y casos sin conexión

### Cambio de Contraseña
- [ ] Crear endpoint call en AuthService
- [ ] Crear pantalla con campos de contraseña actual y nueva
- [ ] Validación en tiempo real
- [ ] Indicador de fortaleza de contraseña
- [ ] Botón para mostrar/ocultar contraseña
- [ ] Manejo de errores (contraseña incorrecta, etc.)

### Cambio de Email
- [ ] Crear endpoint call en UserService
- [ ] Crear pantalla con email actual (read-only) y nuevo
- [ ] Validación de dominio @uniandes.edu.co
- [ ] Campo de contraseña para verificación
- [ ] Detectar cooldown y mostrar días restantes
- [ ] Deshabilitar campos si está en cooldown
- [ ] Manejo de errores

### Status/Incognito
- [ ] Crear enum de status
- [ ] Crear método en UserService para cambiar status
- [ ] Agregar selector de status en Perfil o Settings
- [ ] Mostrar indicador visual del status actual
- [ ] Banner informativo cuando está en incognito
- [ ] Sincronizar status al iniciar app
- [ ] Guardar preferencia localmente (opcional)

---

## Notas técnicas

### State Management
- Usar ViewModel de Android Jetpack o similar para mantener estado
- Implementar LiveData o StateFlow para observables
- Usar corrutinas para operaciones asincrónicas

### API Integration
- Usar Retrofit, Ktor Client, o similar para HTTP requests
- Manejar interceptores para agregar headers de autenticación
- Implementar reintentos automáticos con exponential backoff

### Base de datos local (opcional)
- Cachear notificaciones localmente con Room
- Marcar como leído localmente antes de sincronizar
- Actualizar desde servidor periódicamente

### Testing
- Pruebas unitarias para validación de emails y contraseñas
- Pruebas de integración con mocks del servidor
- Pruebas UI para flujos críticos

---

## Recursos útiles

- [Material Design - Text Fields](https://material.io/components/text-fields)
- [Material Design - Dialogs](https://material.io/components/dialogs)
- [Material Design - Lists](https://material.io/components/lists)
- [Jetpack Compose - TextField](https://developer.android.com/jetpack/compose/text)
- [Android Security Best Practices](https://developer.android.com/training/articles/security-tips)
