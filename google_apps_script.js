
/**
 * Google Apps Script para recibir datos de SearchTracking desde Django
 * y escribirlos en Google Sheets
 */

// Configuración
const SHEET_ID = 'TU_ID_REAL_DE_GOOGLE_SHEETS'; // ⚠️ REEMPLAZA ESTO CON EL ID REAL DE TU HOJA
const SHEET_NAME = 'SearchTracking'; // Nombre de la hoja donde se guardarán los datos

/**
 * Función principal que recibe las requests POST desde Django
 */
function doPost(e) {
  try {
    console.log('=== INICIO doPost ===');
    console.log('Content type:', e.postData.type);
    console.log('Raw data:', e.postData.contents);
    
    // Parsear datos JSON
    const data = JSON.parse(e.postData.contents);
    console.log('Parsed data:', JSON.stringify(data, null, 2));
    
    // Verificar que sea una request de insert_search_tracking
    if (data.action === 'insert_search_tracking') {
      const result = insertSearchTrackingData(data.data);
      
      return ContentService
        .createTextOutput(JSON.stringify({
          success: true,
          message: 'Datos insertados correctamente',
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
    console.log('Primer registro completo:', JSON.stringify(records[0], null, 2));
    
    // Abrir la hoja de cálculo
    const sheet = getOrCreateSheet();
    
    // Preparar headers si la hoja está vacía
    if (sheet.getLastRow() === 0) {
      const headers = [
        'ID', 'Timestamp Búsqueda', 'Check-in', 'Check-out', 'Huéspedes',
        'Cliente ID', 'Cliente Nombre', 'Cliente Apellido', 'Cliente Email', 'Cliente Teléfono',
        'Propiedad ID', 'Propiedad Nombre',
        'IP Address', 'Session Key', 'User Agent', 'Referrer', 'Fecha Creación'
      ];
      sheet.getRange(1, 1, 1, headers.length).setValues([headers]);
      
      // Formatear headers
      const headerRange = sheet.getRange(1, 1, 1, headers.length);
      headerRange.setFontWeight('bold');
      headerRange.setBackground('#e1f5fe');
    }
    
    // Obtener IDs existentes para evitar duplicados
    const existingData = sheet.getDataRange().getValues();
    const existingIds = new Set();
    
    // Empezar desde la fila 2 (skip headers)
    for (let i = 1; i < existingData.length; i++) {
      if (existingData[i][0]) { // Columna ID (índice 0)
        existingIds.add(existingData[i][0].toString());
      }
    }
    
    console.log('IDs existentes en la hoja:', existingIds.size);
    
    // Preparar datos para insertar (solo los nuevos)
    const rows = [];
    let skipped = 0;
    
    records.forEach((record, index) => {
      console.log(`=== PROCESANDO REGISTRO ${index + 1} ===`);
      console.log('Registro completo:', JSON.stringify(record, null, 2));
      
      // Verificar si ya existe este ID
      const recordId = record.id ? record.id.toString() : '';
      
      if (existingIds.has(recordId)) {
        console.log('Saltando registro duplicado:', recordId);
        skipped++;
        return;
      }
      
      // Extraer datos con validación mejorada
      const clientInfo = record.client_info || {};
      const propertyInfo = record.property_info || {};
      const technicalData = record.technical_data || {};
      
      console.log('Client info extraído:', JSON.stringify(clientInfo, null, 2));
      console.log('Property info extraído:', JSON.stringify(propertyInfo, null, 2));
      console.log('Technical data extraído:', JSON.stringify(technicalData, null, 2));
      
      // Extraer cada campo individualmente con logs
      const clientId = clientInfo.id || '';
      const clientFirstName = clientInfo.first_name || '';
      const clientLastName = clientInfo.last_name || '';
      const clientEmail = clientInfo.email || '';
      const clientTelNumber = clientInfo.tel_number || '';
      
      const propertyId = propertyInfo.id || '';
      const propertyName = propertyInfo.name || '';
      
      const ipAddress = technicalData.ip_address || '';
      const sessionKey = technicalData.session_key || '';
      const userAgent = technicalData.user_agent || '';
      const referrer = technicalData.referrer || '';
      
      console.log('Datos extraídos:');
      console.log('- ID:', recordId);
      console.log('- Search timestamp:', record.search_timestamp);
      console.log('- Check-in:', record.check_in_date);
      console.log('- Check-out:', record.check_out_date);
      console.log('- Guests:', record.guests);
      console.log('- Cliente ID:', clientId);
      console.log('- Cliente Nombre:', clientFirstName);
      console.log('- Cliente Apellido:', clientLastName);
      console.log('- Cliente Email:', clientEmail);
      console.log('- Cliente Teléfono:', clientTelNumber);
      console.log('- Propiedad ID:', propertyId);
      console.log('- Propiedad Nombre:', propertyName);
      console.log('- IP:', ipAddress);
      console.log('- Session Key:', sessionKey);
      console.log('- User Agent:', userAgent);
      console.log('- Referrer:', referrer);
      console.log('- Created:', record.created);
      
      const row = [
        recordId,
        record.search_timestamp || '',
        record.check_in_date || '',
        record.check_out_date || '',
        record.guests || '',
        clientId,
        clientFirstName,
        clientLastName,
        clientEmail,
        clientTelNumber,
        propertyId,
        propertyName,
        ipAddress,
        sessionKey,
        userAgent,
        referrer,
        record.created || ''
      ];
      
      console.log('Fila construida:', row);
      rows.push(row);
    });
    
    console.log('=== RESUMEN DE PROCESAMIENTO ===');
    console.log('Registros nuevos a insertar:', rows.length);
    console.log('Registros saltados (duplicados):', skipped);
    console.log('Datos completos de filas:', JSON.stringify(rows, null, 2));
    
    // Insertar todas las filas nuevas de una vez
    if (rows.length > 0) {
      const startRow = sheet.getLastRow() + 1;
      console.log('Insertando en fila:', startRow);
      console.log('Número de filas a insertar:', rows.length);
      console.log('Número de columnas por fila:', rows[0].length);
      
      sheet.getRange(startRow, 1, rows.length, rows[0].length).setValues(rows);
      console.log('¡INSERTADAS!', rows.length, 'filas en Google Sheets');
      
      // Aplicar formato a las nuevas filas
      const newDataRange = sheet.getRange(startRow, 1, rows.length, rows[0].length);
      newDataRange.setBorder(true, true, true, true, true, true);
      
      // Ajustar ancho de columnas automáticamente
      sheet.autoResizeColumns(1, rows[0].length);
    }
    
    return {
      records_processed: rows.length,
      records_skipped: skipped,
      total_records: records.length,
      sheet_name: SHEET_NAME
    };
    
  } catch (error) {
    console.error('Error insertando datos:', error);
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
        'ID', 'Timestamp Búsqueda', 'Check-in', 'Check-out', 'Huéspedes',
        'Cliente ID', 'Cliente Nombre', 'Cliente Apellido', 'Cliente Email', 'Cliente Teléfono',
        'Propiedad ID', 'Propiedad Nombre',
        'IP Address', 'Session Key', 'User Agent', 'Referrer', 'Fecha Creación'
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
      if (existingData[i][0] === record.id) {
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
    
    // Preparar fila de datos
    const row = [
      record.id || '',
      record.search_timestamp || '',
      record.check_in_date || '',
      record.check_out_date || '',
      record.guests || '',
      clientInfo.id || '',
      clientInfo.first_name || '',
      clientInfo.last_name || '',
      clientInfo.email || '',
      clientInfo.tel_number || '',
      propertyInfo.id || '',
      propertyInfo.name || '',
      technicalData.ip_address || '',
      technicalData.session_key || '',
      technicalData.user_agent || '',
      technicalData.referrer || '',
      record.created || ''
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
    const spreadsheet = SpreadsheetApp.openById(SHEET_ID);
    
    // Intentar obtener la hoja existente
    let sheet = spreadsheet.getSheetByName(SHEET_NAME);
    
    // Si no existe, crearla
    if (!sheet) {
      console.log('Creando nueva hoja:', SHEET_NAME);
      sheet = spreadsheet.insertSheet(SHEET_NAME);
      
      // Configurar formato inicial de la hoja
      sheet.setFrozenRows(1); // Congelar fila de headers
    }
    
    return sheet;
    
  } catch (error) {
    console.error('Error accediendo a Google Sheet:', error);
    throw new Error('No se pudo acceder a Google Sheets. Verifica el SHEET_ID.');
  }
}

/**
 * Función de prueba para verificar que el script funciona
 */
function doGet(e) {
  return ContentService
    .createTextOutput(JSON.stringify({
      success: true,
      message: 'Google Apps Script webhook funcionando correctamente',
      timestamp: new Date().toISOString(),
      sheet_id: SHEET_ID,
      sheet_name: SHEET_NAME
    }))
    .setMimeType(ContentService.MimeType.JSON);
}

/**
 * Función de utilidad para testear la inserción manual
 */
function testInsertData() {
  const testData = [
    {
      id: "test-123",
      search_timestamp: new Date().toISOString(),
      check_in_date: "2025-01-15",
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
        name: "Villa Test"
      },
      technical_data: {
        ip_address: "192.168.1.1",
        session_key: "test-session",
        user_agent: "Mozilla/5.0 Test",
        referrer: "https://test.com"
      },
      created: new Date().toISOString()
    }
  ];
  
  const result = insertSearchTrackingData(testData);
  console.log('Test result:', result);
}

/**
 * Función para debug - limpiar hoja y logs detallados
 */
function debugAndTest() {
  try {
    console.log('=== FUNCIÓN DE DEBUG ===');
    
    // Limpiar hoja para empezar de cero
    const sheet = getOrCreateSheet();
    sheet.clear();
    console.log('Hoja limpiada');
    
    // Crear datos de prueba con la estructura exacta que envía Django
    const testData = [
      {
        id: "debug-test-001",
        search_timestamp: "2025-09-01T19:54:58.064000+00:00",
        check_in_date: "2025-09-15",
        check_out_date: "2025-09-17",
        guests: 4,
        client_info: {
          id: "12345678-1234-1234-1234-123456789012",
          first_name: "María",
          last_name: "González",
          email: "maria@example.com",
          tel_number: "+51987654321"
        },
        property_info: {
          id: "prop-987654321-abcd-efgh-ijkl-123456789012",
          name: "Casa Austin Villa Principal"
        },
        technical_data: {
          ip_address: "192.168.1.100",
          session_key: "abc123session456",
          user_agent: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
          referrer: "https://casaaustin.com/search"
        },
        created: "2025-09-01T19:54:50.000000+00:00"
      }
    ];
    
    // Probar inserción
    const result = insertSearchTrackingData(testData);
    console.log('Resultado del test:', JSON.stringify(result, null, 2));
    
    return result;
    
  } catch (error) {
    console.error('Error en función debug:', error);
    throw error;
  }
}

/**
 * Función para limpiar datos antiguos (opcional)
 */
function cleanOldData(daysToKeep = 90) {
  try {
    const sheet = getOrCreateSheet();
    const data = sheet.getDataRange().getValues();
    
    if (data.length <= 1) return; // Solo headers o vacío
    
    const cutoffDate = new Date();
    cutoffDate.setDate(cutoffDate.getDate() - daysToKeep);
    
    // Filtrar filas que se deben mantener (más recientes que cutoffDate)
    const headers = data[0];
    const filteredData = [headers];
    
    for (let i = 1; i < data.length; i++) {
      const timestampStr = data[i][1]; // Columna de timestamp
      if (timestampStr) {
        const recordDate = new Date(timestampStr);
        if (recordDate >= cutoffDate) {
          filteredData.push(data[i]);
        }
      }
    }
    
    // Limpiar la hoja y escribir datos filtrados
    sheet.clear();
    if (filteredData.length > 0) {
      sheet.getRange(1, 1, filteredData.length, filteredData[0].length).setValues(filteredData);
    }
    
    console.log(`Limpieza completada. Registros mantenidos: ${filteredData.length - 1}`);
    
  } catch (error) {
    console.error('Error limpiando datos antiguos:', error);
    throw error;
  }
}

/**
 * Función para limpiar todos los datos (uso con precaución)
 */
function clearAllData() {
  try {
    const sheet = getOrCreateSheet();
    sheet.clear();
    console.log('Todos los datos han sido eliminados de la hoja.');
  } catch (error) {
    console.error('Error limpiando datos:', error);
    throw error;
  }
}
