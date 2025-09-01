
/**
 * Google Apps Script para recibir datos de SearchTracking desde Django
 * y escribirlos en Google Sheets
 */

// Configuración
const SHEET_ID = '1BH3g8h0YXHFJVjUTGUBZAqOGkA_Example'; // Reemplaza con tu ID real de Google Sheets
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
    console.log('Parsed data:', data);
    
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
    console.log('Insertando', records.length, 'registros');
    
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
    
    records.forEach(record => {
      // Verificar si ya existe este ID
      if (existingIds.has(record.id)) {
        console.log('Saltando registro duplicado:', record.id);
        skipped++;
        return;
      }
      
      // Extraer datos correctamente desde la estructura anidada
      const clientInfo = record.client_info || {};
      const propertyInfo = record.property_info || {};
      const technicalData = record.technical_data || {};
      
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
      rows.push(row);
    });
    
    console.log('Registros nuevos a insertar:', rows.length);
    console.log('Registros saltados (duplicados):', skipped);
    
    // Insertar todas las filas nuevas de una vez
    if (rows.length > 0) {
      const startRow = sheet.getLastRow() + 1;
      sheet.getRange(startRow, 1, rows.length, rows[0].length).setValues(rows);
      console.log('Insertadas', rows.length, 'filas en Google Sheets');
      
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
