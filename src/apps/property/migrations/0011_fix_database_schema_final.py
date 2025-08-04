
# Generated manually to fix database schema issues

from django.db import migrations, models
import decimal

class Migration(migrations.Migration):

    dependencies = [
        ('property', '0010_fix_foreign_keys_utf8mb4'),
    ]

    operations = [
        # Deshabilitar verificaciones de foreign keys
        migrations.RunSQL(
            """
            SET FOREIGN_KEY_CHECKS = 0;
            """,
            reverse_sql="SET FOREIGN_KEY_CHECKS = 1;"
        ),
        
        # Verificar y eliminar restricciones de llaves foráneas si existen
        migrations.RunSQL(
            """
            SET @constraint_exists = (
                SELECT COUNT(*)
                FROM information_schema.TABLE_CONSTRAINTS 
                WHERE CONSTRAINT_SCHEMA = DATABASE() 
                AND TABLE_NAME = 'reservation_reservation' 
                AND CONSTRAINT_NAME = 'reservation_reservat_property_id_0d94cf80_fk_property_'
            );
            
            SET @sql = IF(@constraint_exists > 0, 
                'ALTER TABLE reservation_reservation DROP FOREIGN KEY reservation_reservat_property_id_0d94cf80_fk_property_;', 
                'SELECT "Foreign key constraint does not exist";'
            );
            
            PREPARE stmt FROM @sql;
            EXECUTE stmt;
            DEALLOCATE PREPARE stmt;
            """,
            reverse_sql="-- No reverse needed"
        ),
        
        # Sincronizar collations de las tablas relacionadas
        migrations.RunSQL(
            """
            ALTER TABLE property_property CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
            ALTER TABLE reservation_reservation CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
            """,
            reverse_sql="""
            ALTER TABLE property_property CONVERT TO CHARACTER SET utf8 COLLATE utf8_general_ci;
            ALTER TABLE reservation_reservation CONVERT TO CHARACTER SET utf8 COLLATE utf8_general_ci;
            """
        ),
        
        # Agregar el campo precio_desde si no existe
        migrations.RunSQL(
            """
            SET @column_exists = (
                SELECT COUNT(*)
                FROM information_schema.COLUMNS 
                WHERE TABLE_SCHEMA = DATABASE() 
                AND TABLE_NAME = 'property_property' 
                AND COLUMN_NAME = 'precio_desde'
            );
            
            SET @sql = IF(@column_exists = 0, 
                'ALTER TABLE property_property ADD COLUMN precio_desde DECIMAL(10,2) NULL;', 
                'SELECT "Column precio_desde already exists";'
            );
            
            PREPARE stmt FROM @sql;
            EXECUTE stmt;
            DEALLOCATE PREPARE stmt;
            """,
            reverse_sql="ALTER TABLE property_property DROP COLUMN IF EXISTS precio_desde;"
        ),
        
        # Recrear la restricción de llave foránea con collations compatibles
        migrations.RunSQL(
            """
            ALTER TABLE reservation_reservation 
            ADD CONSTRAINT reservation_reservat_property_id_0d94cf80_fk_property_ 
            FOREIGN KEY (property_id) REFERENCES property_property(id) 
            ON DELETE CASCADE ON UPDATE CASCADE;
            """,
            reverse_sql="ALTER TABLE reservation_reservation DROP FOREIGN KEY IF EXISTS reservation_reservat_property_id_0d94cf80_fk_property_;"
        ),
        
        # Rehabilitar verificaciones de foreign keys
        migrations.RunSQL(
            """
            SET FOREIGN_KEY_CHECKS = 1;
            """,
            reverse_sql="SET FOREIGN_KEY_CHECKS = 0;"
        ),
    ]
