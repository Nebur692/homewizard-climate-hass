<div align="center">

<img src="custom_components/homewizard_climate/brand/icon.png" width="96" alt="">

# homewizard-climate-hass

*HomeWizard Climate fans, heaters and dehumidifiers in Home Assistant — pushed live from the cloud, back on their own after any outage*

![Release](https://img.shields.io/github/v/release/Nebur692/homewizard-climate-hass?label=release&color=blue)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![HACS: custom](https://img.shields.io/badge/HACS-custom-41BDF5.svg)](https://hacs.xyz/docs/faq/custom_repositories/)
[![GitHub Sponsors](https://img.shields.io/badge/Sponsor-30363D?logo=githubsponsors&logoColor=EA4AAA)](https://github.com/sponsors/Nebur692)
[![Ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/nebur69265723)
[![PayPal](https://img.shields.io/badge/PayPal-donate-00457C?logo=paypal&logoColor=white)](https://paypal.me/0SkillS)

🇬🇧 [English](#english) · 🇪🇸 [Español](#español)

</div>

---

## English

### ✨ What this is

A maintained fork of [dennis1804/homewizard-climate-hass](https://github.com/dennis1804/homewizard-climate-hass)
for the devices you control with the **HomeWizard Climate** app (Princess fans, heaters, IR panels,
dehumidifiers). The original has had no changes since October 2024 and none of its issues opened
since 2025 has an answer, so this fork rewrites it the way a Home Assistant integration is
written today. It is a drop-in replacement: same domain, same devices, same climate entity ids.

What changes:

| | Original | This fork |
|---|---|---|
| Fans | `climate` entity in "fan only" mode | Native **`fan`** entity: speed, preset, oscillation; voice assistants see a fan |
| Cloud down when Home Assistant starts | Setup fails and stays failed until you reload it | **Retries by itself** |
| Cloud not answering | No timeout: it can hold up startup | **15 s timeout** on every request |
| Connection lost | The last state is shown as if it were current | Entities go **unavailable**, and it reconnects with a growing delay (5 s to 5 min) |
| Device offline in the app | Shown as available | **Unavailable** (the cloud says so in every update) |
| Password changed | Setup fails | Home Assistant **asks for the new password** |
| Connections | One websocket per device, each in its own thread | **One websocket per account**, native asyncio |
| Unknown device type in the account | The whole integration fails to load | That device is left out, with a notice in Repairs; the rest work |
| Crashes | `NotImplementedError` from `preset_mode`, `int()` on `"high"` ([#30](https://github.com/dennis1804/homewizard-climate-hass/issues/30), [#33](https://github.com/dennis1804/homewizard-climate-hass/issues/33), [#34](https://github.com/dennis1804/homewizard-climate-hass/issues/34)) | Values a device does not report show as unknown |
| Same account added twice | Allowed | Refused |
| Dependencies | `homewizard-climate-ws` (`requests`, `websocket-client`, `dataclasses-json`) | None: Home Assistant's own aiohttp |
| Errors you see | Generic | What happened, whether you need to act, and a Burburito code |

Diagnostics download included (no credentials in it).

### 🔁 Upgrading from the original

1. In HACS, remove the original repository (keep the integration configured), add this one as a
   custom repository and install it.
2. Restart Home Assistant.

Your account, devices, areas and climate entities stay as they are. **Fans move from `climate` to
`fan`, keeping the same name**: `climate.bedroom_fan` becomes `fan.bedroom_fan`, with its area,
name, icon, aliases, labels and voice-assistant exposure. If an automation or script still uses
the old entity, a notice in **Settings → Repairs** lists them; change them and it goes away by
itself:

| Before | After |
|---|---|
| `climate.set_hvac_mode` with `hvac_mode: "off"` | `fan.turn_off` |
| `climate.set_hvac_mode` with `hvac_mode: fan_only` | `fan.turn_on` |
| `climate.set_fan_mode` `low` / `medium` / `high` | `fan.set_percentage` 33 / 66 / 100 |
| `climate.set_preset_mode` | `fan.set_preset_mode` |
| `climate.set_swing_mode` | `fan.oscillate` |

### 📦 Installation

1. HACS → ⋮ → **Custom repositories** → `https://github.com/Nebur692/homewizard-climate-hass`,
   type **Integration**.
2. Install **HomeWizard Climate** and restart Home Assistant.
3. **Settings → Devices & services → Add integration → HomeWizard Climate**, with the email and
   password of the HomeWizard Climate app.

Needs Home Assistant 2026.10 or newer.

### 🧭 Supported devices

| Type in the cloud | Entity |
|---|---|
| `fan` | fan (3 speeds, presets normal / sleep / natural, oscillation) |
| `heaterfan`, `airconditioner` | climate (heat / cool / off, fan speed, swing, target temperature) |
| `heater` | climate (heat / off, eco and boost presets, target temperature) |
| `infraredheater` | climate (heat / off, target temperature) |
| `dehumidifier` | climate (target humidity, presets, fan speed, swing) |

Fans are tested against a live account. The other types keep the behaviour of the original
integration, now covered by tests against a simulated cloud; if yours behaves differently, open an
issue with the diagnostics download.

### 🩹 Troubleshooting

- **Entities unavailable**: the device is offline in the HomeWizard app, or the cloud connection is
  down; it reconnects by itself.
- **A device is missing**: look in **Settings → Repairs**. If its type is not supported yet, the
  notice says which type; open an issue with it.
- Every error message ends with a **Burburito code** (`028-…`): include it in your issue.

### 💙 Support

None of this would be possible without the community's support. If this project has been useful to
you, consider supporting it on [Ko-fi](https://ko-fi.com/nebur69265723) or
[PayPal](https://paypal.me/0SkillS) — every bit helps keep it maintained.

### 📜 License

MIT, see [LICENSE](LICENSE). The code of version 2 is a new implementation; the original repository had no license.

### 🙏 Credits

Original integration by [dennis1804](https://github.com/dennis1804/homewizard-climate-hass) and
contributors. The cloud protocol comes from
[homewizard-climate-websocket](https://github.com/mepla/homewizard-climate-websocket) by mepla (MIT).

### ⚠️ Disclaimer

Not affiliated with HomeWizard, Princess or Home Assistant.

---

## Español

### ✨ Qué es

Un fork mantenido de [dennis1804/homewizard-climate-hass](https://github.com/dennis1804/homewizard-climate-hass)
para los aparatos que manejas con la app **HomeWizard Climate** (ventiladores, estufas, paneles de
infrarrojos y deshumidificadores de Princess). El original no tiene cambios desde octubre de 2024 y
ninguno de los tickets abiertos desde 2025 tiene respuesta, así que este fork lo reescribe como se
escribe hoy una integración de Home Assistant. Lo sustituye sin más: mismo dominio, mismos
aparatos y mismos ids de las entidades de clima.

Lo que cambia:

| | Original | Este fork |
|---|---|---|
| Ventiladores | Entidad `climate` en modo «solo ventilador» | Entidad **`fan`** nativa: velocidad, modo y oscilación; los asistentes de voz ven un ventilador |
| La nube caída al arrancar Home Assistant | Falla y se queda fallando hasta que la recargas | **Se reintenta sola** |
| La nube no contesta | Sin límite de tiempo: puede frenar el arranque | **15 s de límite** en cada petición |
| Se pierde la conexión | Enseña el último estado como si fuera el de ahora | Las entidades pasan a **no disponibles** y reconecta con espera creciente (de 5 s a 5 min) |
| Aparato desconectado en la app | Aparece disponible | **No disponible** (la nube lo dice en cada actualización) |
| Cambias la contraseña | Falla | Home Assistant **te pide la nueva** |
| Conexiones | Un websocket por aparato, cada uno en su hilo | **Un websocket por cuenta**, asyncio nativo |
| Tipo de aparato desconocido en la cuenta | No carga la integración entera | Ese aparato se queda fuera con un aviso en Reparaciones; los demás funcionan |
| Cuelgues | `NotImplementedError` en `preset_mode`, `int()` sobre `"high"` ([#30](https://github.com/dennis1804/homewizard-climate-hass/issues/30), [#33](https://github.com/dennis1804/homewizard-climate-hass/issues/33), [#34](https://github.com/dennis1804/homewizard-climate-hass/issues/34)) | Lo que un aparato no informa sale como desconocido |
| La misma cuenta dos veces | Se permite | Se rechaza |
| Dependencias | `homewizard-climate-ws` (`requests`, `websocket-client`, `dataclasses-json`) | Ninguna: el aiohttp del propio Home Assistant |
| Los errores que ves | Genéricos | Qué ha pasado, si tienes que hacer algo y un código burburito |

Incluye descarga de diagnóstico (sin credenciales).

### 🔁 Si vienes del original

1. En HACS, quita el repositorio original (deja la integración configurada), añade este como
   repositorio personalizado e instálalo.
2. Reinicia Home Assistant.

La cuenta, los aparatos, las áreas y las entidades de clima se quedan como estaban. **Los
ventiladores pasan de `climate` a `fan` con el mismo nombre**: `climate.ventilador_cama` pasa a ser
`fan.ventilador_cama`, con su área, nombre, icono, alias, etiquetas y lo que tuvieras configurado
para los asistentes de voz. Si alguna automatización o script sigue usando la entidad vieja, un
aviso en **Ajustes → Reparaciones** te dice cuáles; cuando las cambies, se quita solo:

| Antes | Ahora |
|---|---|
| `climate.set_hvac_mode` con `hvac_mode: "off"` | `fan.turn_off` |
| `climate.set_hvac_mode` con `hvac_mode: fan_only` | `fan.turn_on` |
| `climate.set_fan_mode` `low` / `medium` / `high` | `fan.set_percentage` 33 / 66 / 100 |
| `climate.set_preset_mode` | `fan.set_preset_mode` |
| `climate.set_swing_mode` | `fan.oscillate` |

### 📦 Instalación

1. HACS → ⋮ → **Repositorios personalizados** → `https://github.com/Nebur692/homewizard-climate-hass`,
   tipo **Integración**.
2. Instala **HomeWizard Climate** y reinicia Home Assistant.
3. **Ajustes → Dispositivos y servicios → Añadir integración → HomeWizard Climate**, con el correo y
   la contraseña de la app HomeWizard Climate.

Necesita Home Assistant 2026.10 o posterior.

### 🧭 Aparatos soportados

| Tipo en la nube | Entidad |
|---|---|
| `fan` | ventilador (3 velocidades, modos normal / dormir / natural, oscilación) |
| `heaterfan`, `airconditioner` | clima (calor / frío / apagado, velocidad, oscilación, temperatura objetivo) |
| `heater` | clima (calor / apagado, modos eco y boost, temperatura objetivo) |
| `infraredheater` | clima (calor / apagado, temperatura objetivo) |
| `dehumidifier` | clima (humedad objetivo, modos, velocidad, oscilación) |

Los ventiladores están probados contra una cuenta real. Los demás tipos mantienen el
comportamiento de la integración original, ahora cubierto con pruebas contra una nube simulada; si
el tuyo se porta distinto, abre un ticket con la descarga de diagnóstico.

### 🩹 Problemas frecuentes

- **Entidades no disponibles**: el aparato está desconectado en la app de HomeWizard, o se ha
  caído la conexión con la nube; reconecta sola.
- **Falta un aparato**: mira en **Ajustes → Reparaciones**. Si su tipo aún no está soportado, el
  aviso dice cuál es; abre un ticket con él.
- Cada mensaje de error termina con un **código burburito** (`028-…`): ponlo en el ticket.

### 💙 Apoya el proyecto

Sin el apoyo de la comunidad estos proyectos no serían posibles. Si te ha resultado útil, puedes
apoyarlo en [Ko-fi](https://ko-fi.com/nebur69265723) o [PayPal](https://paypal.me/0SkillS) —
cualquier aportación ayuda a seguir manteniéndolo.

### 📜 Licencia

MIT, mira [LICENSE](LICENSE). El código de la versión 2 es una implementación nueva; el repositorio original no tenía licencia.

### 🙏 Créditos

La integración original es de [dennis1804](https://github.com/dennis1804/homewizard-climate-hass) y
sus colaboradores. El protocolo de la nube viene de
[homewizard-climate-websocket](https://github.com/mepla/homewizard-climate-websocket), de mepla (MIT).

### ⚠️ Aviso

Sin relación con HomeWizard, Princess ni Home Assistant.
