/**
 * Google Apps Script para recibir datos de SearchTracking desde Django
 * y escribirlos en Google Sheets
 */

// Configuración
const SHEET_ID = '1CxliaXMZPmLOc_OkPRezdpdTw2ix9r9Fw4oQNkCR4J0'; // ✅ ID real de tu Google Sheets
const SHEET_NAME = 'Hoja 1'; // ✅ Usar el nombre real de tu pestaña

/**
 * Función principal que recibe las requests POST desde Django
 */
function doPost(e) {
  try {
    console.log('=== INICIO doPost ===');
    console.log('Content type:', e.postData ? e.postData.type : 'NO POST DATA');
    console.log('Raw data length:', e.postData ? e.postData.contents.length : 0);
    console.log('Raw data (primeros 500 chars):', e.postData ? e.postData.contents.substring(0, 500) : 'NO DATA');

    if (!e.postData || !e.postData.contents) {
      console.error('ERROR: No se recibieron datos POST');
      return ContentService
        .createTextOutput(JSON.stringify({
          success: false,
          message: 'No se recibieron datos en la request',
          timestamp: new Date().toISOString()
        }))
        .setMimeType(ContentService.MimeType.JSON);
    }

    // Parsear datos JSON
    let data;
    try {
      data = JSON.parse(e.postData.contents);
      console.log('=== DATOS PARSEADOS EXITOSAMENTE ===');
      console.log('Action:', data.action);
      console.log('Timestamp:', data.timestamp);
      console.log('Data type:', typeof data.data);
      console.log('Data length:', Array.isArray(data.data) ? data.data.length : 'NO ES ARRAY');
      console.log('Primer registro:', data.data && data.data.length > 0 ? JSON.stringify(data.data[0], null, 2) : 'NO HAY DATOS');
    } catch (parseError) {
      console.error('ERROR PARSEANDO JSON:', parseError);
      console.error('Contenido que falló:', e.postData.contents);
      return ContentService
        .createTextOutput(JSON.stringify({
          success: false,
          message: 'Error parseando JSON: ' + parseError.toString(),
          timestamp: new Date().toISOString()
        }))
        .setMimeType(ContentService.MimeType.JSON);
    }

    // Verificar que sea una request de insert_search_tracking
    if (data.action === 'insert_search_tracking') {
      console.log('=== ACCIÓN RECONOCIDA: insert_search_tracking ===');

      if (!data.data || !Array.isArray(data.data)) {
        console.error('ERROR: data.data no es un array válido');
        return ContentService
          .createTextOutput(JSON.stringify({
            success: false,
            message: 'data.data debe ser un array',
            received_data_type: typeof data.data,
            timestamp: new Date().toISOString()
          }))
          .setMimeType(ContentService.MimeType.JSON);
      }

      console.log(`Procesando ${data.data.length} registros...`);
      const result = insertSearchTrackingData(data.data);

      return ContentService
        .createTextOutput(JSON.stringify({
          success: true,
          message: 'Datos guardados en Google Sheets',
          records_processed: result.records_processed,
          records_skipped: result.records_skipped,
          timestamp: new Date().toISOString()
        }))
        .setMimeType(ContentService.MimeType.JSON);
    }

    // Para otras acciones o datos individuales
    const result = insertSingleRecord(data);

    return ContentService
      .createTextOutput(JSON.stringify({
        success: true,
        message: 'Registro individual insertado',
        record_id: result.record_id
      }))
      .setMimeType(ContentService.MimeType.JSON);

  } catch (error) {
    console.error('Error en doPost:', error);

    return ContentService
      .createTextOutput(JSON.stringify({
        success: false,
        message: 'Error procesando datos: ' + error.toString(),
        timestamp: new Date().toISOString()
      }))
      .setMimeType(ContentService.MimeType.JSON);
  }
}

/**
 * Función para insertar múltiples registros de SearchTracking
 */
function insertSearchTrackingData(records) {
  try {
    console.log('=== INICIANDO INSERCIÓN ===');
    console.log('Número de registros recibidos:', records.length);

    if (!records || records.length === 0) {
      console.log('No hay registros para procesar');
      return {
        records_processed: 0,
        records_skipped: 0,
        total_records: 0
      };
    }

    console.log('Primer registro completo:', JSON.stringify(records[0], null, 2));

    // Abrir la hoja de cálculo
    const sheet = getOrCreateSheet();

    // Preparar headers si la hoja está vacía
    if (sheet.getLastRow() === 0) {
      console.log('Hoja vacía, agregando headers...');
      const headers = [
        'Timestamp Búsqueda', 'ID', 'Check-in', 'Check-out', 'Tipo de Día', 'Noches', 'Huéspedes',
        'Cliente ID', 'Cliente Nombre', 'Cliente Apellido', 'Cliente Email', 'Cliente Teléfono',
        'Propiedad ID', 'Propiedad Nombre',
        'IP Address', 'Session Key', 'User Agent', 'Referrer', '0Fecha de búsqueda'
      ];
      sheet.getRange(1, 1, 1, headers.length).setValues([headers]);

      // Formatear headers
      const headerRange = sheet.getRange(1, 1, 1, headers.length);
      headerRange.setFontWeight('bold');
      headerRange.setBackground('#e1f5fe');
      console.log('Headers agregados y formateados');
    } else {
      console.log('Hoja ya tiene datos, ultima fila:', sheet.getLastRow());
    }

    // Obtener IDs existentes para evitar duplicados
    const existingData = sheet.getDataRange().getValues();
    const existingIds = new Set();

    // Empezar desde la fila 2 (skip headers)
    for (let i = 1; i < existingData.length; i++) {
      if (existingData[i][1]) { // Columna ID (índice 1)
        existingIds.add(existingData[i][1].toString());
      }
    }

    console.log('IDs existentes en la hoja:', existingIds.size);

    // Preparar datos para insertar (solo los nuevos)
    const rows = [];
    let skipped = 0;

    records.forEach((record, index) => {
      console.log(`=== PROCESANDO REGISTRO ${index + 1}/${records.length} ===`);

      // Verificar si ya existe este ID
      const recordId = record.id ? record.id.toString() : `temp-${Date.now()}-${index}`;

      if (existingIds.has(recordId)) {
        console.log('Saltando registro duplicado:', recordId);
        skipped++;
        return;
      }

      // Extraer datos con validación mejorada
      const clientInfo = record.client_info || {};
      const propertyInfo = record.property_info || {};
      const technicalData = record.technical_data || {};

      console.log('Datos del registro:');
      console.log('- ID:', recordId);
      console.log('- Cliente:', clientInfo.first_name, clientInfo.last_name);
      console.log('- Email:', clientInfo.email);
      console.log('- Propiedad:', propertyInfo.name);
      console.log('- Check-in:', record.check_in_date);
      console.log('- Check-out:', record.check_out_date);
      console.log('- Huéspedes:', record.guests);

      // Formatear timestamp de búsqueda - formato timestamp completo
      const searchTimestamp = record.search_timestamp ?
        formatDateToGMT5(record.search_timestamp) : 'Sin fecha';

      // Formatear check-in y check-out - solo fecha
      const checkInFormatted = record.check_in_date ?
        formatDateOnly(record.check_in_date) : 'Sin fecha';

      const checkOutFormatted = record.check_out_date ?
        formatDateOnly(record.check_out_date) : 'Sin fecha';

      // Formatear fecha de creación - solo fecha (renombrada a 0Fecha de búsqueda)
      const createdFormatted = record.created ?
        formatDateOnly(record.created) : 'Sin fecha';

      // Determinar tipo de día basado en check-in
      let tipoDia = 'Sin fecha';
      if (record.check_in_date) {
        const checkInDate = new Date(record.check_in_date);
        const dayOfWeek = checkInDate.getDay(); // 0=Domingo, 1=Lunes, ..., 6=Sábado
        tipoDia = (dayOfWeek === 5 || dayOfWeek === 6) ? 'Fin de semana' : 'Día de semana';
      }

      // Calcular número de noches
      let noches = 0;
      if (record.check_in_date && record.check_out_date) {
        const checkIn = new Date(record.check_in_date);
        const checkOut = new Date(record.check_out_date);
        noches = Math.max(0, Math.floor((checkOut - checkIn) / (1000 * 60 * 60 * 24)));
      }

      // Preparar fila con timestamp de búsqueda como primera columna
      const row = [
        searchTimestamp, // Primera columna: Timestamp Búsqueda
        record.id || 'Sin ID',
        checkInFormatted,
        checkOutFormatted,
        tipoDia,
        noches,
        record.guests || 0,
        clientInfo.id || 'ANONIMO',
        clientInfo.first_name || 'Usuario',
        clientInfo.last_name || 'Anónimo',
        clientInfo.email || 'anonimo@casaaustin.pe',
        clientInfo.tel_number || 'Sin teléfono',
        propertyInfo.id || 'SIN_PROPIEDAD',
        propertyInfo.name || 'Búsqueda general',
        technicalData.ip_address || 'Sin IP',
        technicalData.session_key || 'Sin sesión',
        technicalData.user_agent || 'Sin user agent',
        technicalData.referrer || 'Sin referrer',
        createdFormatted // Última columna: 0Fecha de búsqueda
      ];

      console.log('Fila construida con', row.length, 'columnas');
      rows.push(row);
    });

    console.log('=== RESUMEN DE PROCESAMIENTO ===');
    console.log('Registros nuevos a insertar:', rows.length);
    console.log('Registros saltados (duplicados):', skipped);

    // Insertar todas las filas nuevas de una vez
    if (rows.length > 0) {
      const startRow = sheet.getLastRow() + 1;
      console.log('Insertando en fila:', startRow);
      console.log('Número de filas a insertar:', rows.length);
      console.log('Número de columnas por fila:', rows[0].length);

      try {
        // Insertar los datos
        sheet.getRange(startRow, 1, rows.length, rows[0].length).setValues(rows);
        console.log('✅ DATOS INSERTADOS EXITOSAMENTE!');

        // Aplicar formato a las nuevas filas
        const newDataRange = sheet.getRange(startRow, 1, rows.length, rows[0].length);
        newDataRange.setBorder(true, true, true, true, true, true);

        // Ajustar ancho de columnas automáticamente
        sheet.autoResizeColumns(1, rows[0].length);

        console.log('✅ FORMATO APLICADO EXITOSAMENTE!');

      } catch (insertError) {
        console.error('❌ ERROR AL INSERTAR DATOS:', insertError);
        throw insertError;
      }
    } else {
      console.log('⚠️ No hay registros nuevos para insertar');
    }

    const result = {
      records_processed: rows.length,
      records_skipped: skipped,
      total_records: records.length,
      sheet_name: SHEET_NAME,
      sheet_last_row: sheet.getLastRow()
    };

    console.log('=== RESULTADO FINAL ===', result);
    return result;

  } catch (error) {
    console.error('❌ ERROR CRÍTICO insertando datos:', error);
    console.error('Error stack:', error.stack);
    throw error;
  }
}

/**
 * Función para insertar un registro individual
 */
function insertSingleRecord(record) {
  try {
    console.log('Insertando registro individual:', record.id);

    const sheet = getOrCreateSheet();

    // Si la hoja está vacía, agregar headers
    if (sheet.getLastRow() === 0) {
      const headers = [
        'Timestamp Búsqueda', 'ID', 'Check-in', 'Check-out', 'Tipo de Día', 'Noches', 'Huéspedes',
        'Cliente ID', 'Cliente Nombre', 'Cliente Apellido', 'Cliente Email', 'Cliente Teléfono',
        'Propiedad ID', 'Propiedad Nombre',
        'IP Address', 'Session Key', 'User Agent', 'Referrer', '0Fecha de búsqueda'
      ];
      sheet.getRange(1, 1, 1, headers.length).setValues([headers]);

      // Formatear headers
      const headerRange = sheet.getRange(1, 1, 1, headers.length);
      headerRange.setFontWeight('bold');
      headerRange.setBackground('#e1f5fe');
    }

    // Verificar si ya existe este registro
    const existingData = sheet.getDataRange().getValues();
    for (let i = 1; i < existingData.length; i++) {
      if (existingData[i][1] === record.id) { // Columna ID ahora está en índice 1
        console.log('Registro ya existe:', record.id);
        return {
          record_id: record.id,
          sheet_name: SHEET_NAME,
          action: 'skipped_duplicate'
        };
      }
    }

    // Extraer datos correctamente desde la estructura anidada
    const clientInfo = record.client_info || {};
    const propertyInfo = record.property_info || {};
    const technicalData = record.technical_data || {};

    // Formatear timestamp de búsqueda - formato timestamp completo
    const searchTimestamp = record.search_timestamp ?
      formatDateToGMT5(record.search_timestamp) : 'Sin fecha';

    // Formatear check-in y check-out - solo fecha
    const checkInFormatted = record.check_in_date ?
      formatDateOnly(record.check_in_date) : 'Sin fecha';

    const checkOutFormatted = record.check_out_date ?
      formatDateOnly(record.check_out_date) : 'Sin fecha';

    // Formatear fecha de creación - solo fecha (renombrada a 0Fecha de búsqueda)
    const createdFormatted = record.created ?
      formatDateOnly(record.created) : 'Sin fecha';

    // Determinar Tipo de Día (Fin de semana o Día de semana)
    let tipoDeDia = 'Sin fecha';
    if (record.check_in_date) {
      try {
        const checkInDate = new Date(record.check_in_date);
        const dayOfWeek = checkInDate.getDay(); // 0 = Domingo, 6 = Sábado
        if (dayOfWeek === 5 || dayOfWeek === 6) { // Viernes o Sábado
          tipoDeDia = 'Fin de semana';
        }
      } catch (e) {
        console.error('Error al determinar tipo de día:', e);
      }
    }

    // Calcular Cantidad de Noches
    let noches = '';
    if (record.check_in_date && record.check_out_date) {
      try {
        const checkIn = new Date(record.check_in_date);
        const checkOut = new Date(record.check_out_date);
        const timeDiff = checkOut.getTime() - checkIn.getTime();
        noches = Math.ceil(timeDiff / (1000 * 3600 * 24));
      } catch (e) {
        console.error('Error al calcular noches:', e);
      }
    }

    // Preparar fila de datos
    const row = [
      searchTimestamp,   // Primera columna: Timestamp Búsqueda
      record.id || 'Sin ID',
      checkInFormatted,
      checkOutFormatted,
      tipoDeDia,
      noches,
      record.guests || '',
      clientInfo.id || 'ANONIMO',
      clientInfo.first_name || 'Usuario',
      clientInfo.last_name || 'Anónimo',
      clientInfo.email || 'anonimo@casaaustin.pe',
      clientInfo.tel_number || 'Sin teléfono',
      propertyInfo.id || 'SIN_PROPIEDAD',
      propertyInfo.name || 'Búsqueda general',
      technicalData.ip_address || 'Sin IP',
      technicalData.session_key || 'Sin sesión',
      technicalData.user_agent || 'Sin user agent',
      technicalData.referrer || 'Sin referrer',
      createdFormatted // Última columna: 0Fecha de búsqueda
    ];

    // Insertar fila
    sheet.appendRow(row);

    // Aplicar formato a la nueva fila
    const lastRow = sheet.getLastRow();
    const newRowRange = sheet.getRange(lastRow, 1, 1, row.length);
    newRowRange.setBorder(true, true, true, true, true, true);

    return {
      record_id: record.id,
      sheet_name: SHEET_NAME,
      action: 'inserted'
    };

  } catch (error) {
    console.error('Error insertando registro individual:', error);
    throw error;
  }
}

/**
 * Obtener o crear la hoja de SearchTracking
 */
function getOrCreateSheet() {
  try {
    console.log('=== ACCEDIENDO A GOOGLE SHEETS ===');
    console.log('SHEET_ID:', SHEET_ID);
    console.log('SHEET_NAME:', SHEET_NAME);

    const spreadsheet = SpreadsheetApp.openById(SHEET_ID);
    console.log('✅ Spreadsheet abierto exitosamente');
    console.log('Nombre del spreadsheet:', spreadsheet.getName());

    // Intentar obtener la hoja existente
    let sheet = spreadsheet.getSheetByName(SHEET_NAME);

    if (!sheet) {
      console.log('❌ Hoja no encontrada, creando nueva hoja:', SHEET_NAME);
      sheet = spreadsheet.insertSheet(SHEET_NAME);

      // Configurar formato inicial de la hoja
      sheet.setFrozenRows(1); // Congelar fila de headers
      console.log('✅ Nueva hoja creada y configurada');
    } else {
      console.log('✅ Hoja existente encontrada:', SHEET_NAME);
      console.log('Última fila con datos:', sheet.getLastRow());
    }

    return sheet;

  } catch (error) {
    console.error('❌ ERROR CRÍTICO accediendo a Google Sheet:', error);
    console.error('Error stack:', error.stack);
    throw new Error('No se pudo acceder a Google Sheets. Verifica el SHEET_ID: ' + error.toString());
  }
}

/**
 * Función de prueba para verificar que el script funciona
 */
function doGet(e) {
  try {
    console.log('=== TEST doGet ===');
    const sheet = getOrCreateSheet();

    return ContentService
      .createTextOutput(JSON.stringify({
        success: true,
        message: 'Google Apps Script webhook funcionando correctamente',
        timestamp: new Date().toISOString(),
        sheet_id: SHEET_ID,
        sheet_name: SHEET_NAME,
        sheet_last_row: sheet.getLastRow(),
        spreadsheet_name: SpreadsheetApp.openById(SHEET_ID).getName()
      }))
      .setMimeType(ContentService.MimeType.JSON);
  } catch (error) {
    return ContentService
      .createTextOutput(JSON.stringify({
        success: false,
        message: 'Error en test: ' + error.toString(),
        timestamp: new Date().toISOString()
      }))
      .setMimeType(ContentService.MimeType.JSON);
  }
}

/**
 * Función de utilidad para testear la inserción manual
 */
function testInsertData() {
  const testData = [
    {
      id: "test-manual-" + new Date().getTime(),
      search_timestamp: new Date().toISOString(),
      check_in_date: "2025-01-15", // Miércoles
      check_out_date: "2025-01-17",
      guests: 2,
      client_info: {
        id: "client-456",
        first_name: "Juan",
        last_name: "Pérez",
        email: "juan@example.com",
        tel_number: "+51999888777"
      },
      property_info: {
        id: "prop-789",
        name: "Villa Test Manual"
      },
      technical_data: {
        ip_address: "192.168.1.1",
        session_key: "test-session-manual",
        user_agent: "Mozilla/5.0 Test Manual",
        referrer: "https://test-manual.com"
      },
      created: new Date().toISOString()
    },
    {
      id: "test-manual-weekend-" + new Date().getTime(),
      search_timestamp: new Date().toISOString(),
      check_in_date: "2025-01-17", // Viernes
      check_out_date: "2025-01-20", // Lunes
      guests: 4,
      client_info: {
        id: "client-789",
        first_name: "Ana",
        last_name: "García",
        email: "ana@example.com",
        tel_number: "+51888777666"
      },
      property_info: {
        id: "prop-123",
        name: "Casa Fin de Semana"
      },
      technical_data: {
        ip_address: "192.168.1.2",
        session_key: "test-session-weekend",
        user_agent: "Mozilla/5.0 Test Weekend",
        referrer: "https://test-weekend.com"
      },
      created: new Date().toISOString()
    }
  ];

  console.log('=== EJECUTANDO TEST MANUAL ===');
  const result = insertSearchTrackingData(testData);
  console.log('✅ Test result:', result);
  return result;
}

/**
 * Función para limpiar todos los datos (uso con precaución)
 */
function clearAllData() {
  try {
    const sheet = getOrCreateSheet();
    sheet.clear();
    console.log('✅ Todos los datos han sido eliminados de la hoja.');
    return { success: true, message: 'Datos eliminados' };
  } catch (error) {
    console.error('❌ Error limpiando datos:', error);
    throw error;
  }
}

/**
 * Función para obtener información de la hoja
 */
function getSheetInfo() {
  try {
    const sheet = getOrCreateSheet();
    const spreadsheet = SpreadsheetApp.openById(SHEET_ID);

    return {
      spreadsheet_name: spreadsheet.getName(),
      sheet_name: sheet.getName(),
      last_row: sheet.getLastRow(),
      last_column: sheet.getLastColumn(),
      data_range: sheet.getDataRange().getA1Notation(),
      sheet_id: SHEET_ID
    };
  } catch (error) {
    console.error('Error obteniendo info de la hoja:', error);
    throw error;
  }
}

/**
 * Formatea una fecha a formato DD/MM/YYYY HH:MM:SS en zona horaria GMT-5
 * @param {string} isoString Fecha en formato ISO (ej. "2023-10-27T10:00:00.000Z")
 * @returns {string} Fecha formateada o 'Sin fecha' si la entrada es inválida.
 */
function formatDateToGMT5(isoString) {
  if (!isoString) {
    return 'Sin fecha';
  }
  try {
    // Para fechas ISO que ya vienen en GMT-5, no aplicar conversión adicional
    if (isoString.includes('+00:00') || isoString.includes('Z')) {
      // Es una fecha UTC, convertir a GMT-5
      const date = new Date(isoString);
      if (isNaN(date.getTime())) {
        console.warn(`Fecha inválida recibida para formatear: ${isoString}`);
        return isoString;
      }
      return Utilities.formatDate(date, 'GMT-5', 'dd/MM/yyyy HH:mm:ss');
    } else {
      // Es una fecha que ya está en hora local, parsear directamente
      const date = new Date(isoString);
      if (isNaN(date.getTime())) {
        console.warn(`Fecha inválida recibida para formatear: ${isoString}`);
        return isoString;
      }
      // No aplicar conversión de zona horaria, usar la fecha tal como viene
      return Utilities.formatDate(date, 'America/Lima', 'dd/MM/yyyy HH:mm:ss');
    }
  } catch (e) {
    console.error(`Error formateando fecha ${isoString}: ${e}`);
    return isoString;
  }
}

/**
 * Formatea una fecha a formato DD/MM/YYYY (solo fecha) sin conversión de zona horaria
 * @param {string} isoString Fecha en formato ISO o YYYY-MM-DD
 * @returns {string} Fecha formateada o 'Sin fecha'.
 */
function formatDateOnly(isoString) {
  if (!isoString) {
    return 'Sin fecha';
  }
  try {
    // Si es una fecha simple YYYY-MM-DD, parsear directamente sin conversión
    if (isoString.match(/^\d{4}-\d{2}-\d{2}$/)) {
      const parts = isoString.split('-');
      const day = parts[2];
      const month = parts[1];
      const year = parts[0];
      return `${day}/${month}/${year}`;
    }
    
    // Para fechas ISO completas
    if (isoString.includes('+00:00') || isoString.includes('Z')) {
      // Es una fecha UTC, convertir a GMT-5
      const date = new Date(isoString);
      if (isNaN(date.getTime())) {
        console.warn(`Fecha inválida recibida para formatear (solo fecha): ${isoString}`);
        return isoString;
      }
      return Utilities.formatDate(date, 'GMT-5', 'dd/MM/yyyy');
    } else {
      // Es una fecha que ya está en hora local
      const date = new Date(isoString);
      if (isNaN(date.getTime())) {
        console.warn(`Fecha inválida recibida para formatear (solo fecha): ${isoString}`);
        return isoString;
      }
      // No aplicar conversión de zona horaria
      return Utilities.formatDate(date, 'America/Lima', 'dd/MM/yyyy');
    }
  } catch (e) {
    console.error(`Error formateando fecha (solo fecha) ${isoString}: ${e}`);
    return isoString;
  }
}