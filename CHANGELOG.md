# CHANGELOG - Bot de Medidas Eléctricas

## v2.1.0 - [2025-06-10] OPTIMIZACIÓN Y CORRECCIONES

### 🚀 Rendimiento
- **Diagrama_engine**: Reducido DPI de 160 → 120 (40% más rápido)
- **Caché de diagramas**: Almacenamiento temporal con hash(config) para evitar regenerar
- **Tiempos generación**:
  - Conexiones: **0.5s** (antes ~2-3s)
  - Unifilar simple: **0.06-0.09s** (antes ~1.5s)
  - Unifilar con trafo: **0.06s** (antes ~1.5s)

### 🔧 Correcciones críticas

#### Parser.py
- ✅ **FIX**: Detectaba "directa" dentro de "indirecta" → Regex con word boundaries `\b`
- ✅ **ADD**: Validación de tipo ambiguo (lanza ValueError)
- ✅ **IMPROVE**: Mejor detección de sistema (mono/bifasico/tri3h/tri4h)
- ✅ **ADD**: Validación de entrada (lanza ValueError si especificacion vacía)

#### Bot.py
- ✅ **FIX**: Menu callback error - pasaba `q` en lugar de `update` a _enviar()
- ✅ **ADD**: DEBUG logging en todas las funciones críticas
- ✅ **IMPROVE**: Manejo de errores específicos (ValueError, TimeoutError, Exception)
- ✅ **IMPROVE**: Mensajes de usuario más informativos con emojis
- ✅ **ADD**: Logging en cmd_diagrama para seguimiento de solicitudes
- ✅ **ADD**: Validación en _generar() con try/except mejorado

#### Diagram_engine.py
- ✅ **ADD**: Caché local con MD5 hash de config
- ✅ **ADD**: DPI configurable (constante DPI = 120)
- ✅ **IMPROVE**: Estructura modular con funciones _get_cached() y _save_cached()
- ✅ **UPDATE**: Todos los plt.savefig() ahora usan DPI optimizado

### 📋 Casos de uso probados
```
✓ Parser: indirecta tri4h 200/5 13200/120 CENS
✓ Parser: semidirecta 300/5 RA8
✓ Parser: directa monofasica
✓ Diagrama conexiones: generado en 0.51s
✓ Unifilar simple: generado en 0.09s
✓ Unifilar con trafo: generado en 0.06s
```

### 📝 Notas de migración
- No hay cambios en API externa
- Caché automática transparente
- Compatible con versiones previas de config

### 🐛 Bugs conocidos (ya corregidos)
- [x] Menu no generaba diagrama
- [x] Parser detectaba false positives en tipo
- [x] Timeout de generación muy lento
- [x] Sin logging para debugging

### 🔮 Próximos pasos recomendados
- [ ] Diagrama fasorial (tercera salida del bot)
- [ ] Numeración exacta de bornes B1–B26 (RA8)
- [ ] 2 elementos con 2 TP línea-línea
- [ ] Tests unitarios del parser
