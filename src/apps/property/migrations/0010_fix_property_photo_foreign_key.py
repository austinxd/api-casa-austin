
from django.db import migrations, models
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ('property', '0009_add_property_photos'),
    ]

    operations = [
        # Verificar y eliminar constraint si existe
        migrations.RunSQL(
            """
            SET @constraint_name = (
                SELECT CONSTRAINT_NAME 
                FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE 
                WHERE TABLE_SCHEMA = DATABASE() 
                AND TABLE_NAME = 'property_propertyphoto' 
                AND COLUMN_NAME = 'property_id' 
                AND CONSTRAINT_NAME LIKE '%fk%'
                LIMIT 1
            );
            SET @sql = IF(@constraint_name IS NOT NULL, 
                CONCAT('ALTER TABLE property_propertyphoto DROP FOREIGN KEY ', @constraint_name), 
                'SELECT "No foreign key constraint found" as message'
            );
            PREPARE stmt FROM @sql;
            EXECUTE stmt;
            DEALLOCATE PREPARE stmt;
            """,
            reverse_sql="-- No reverse SQL needed"
        ),
        
        # Cambiar el tipo de columna property_id para que coincida con Property.id (UUID)
        migrations.RunSQL(
            "ALTER TABLE property_propertyphoto MODIFY COLUMN property_id CHAR(32) NOT NULL;",
            reverse_sql="ALTER TABLE property_propertyphoto MODIFY COLUMN property_id INT NOT NULL;"
        ),
        
        # Agregar nuevo constraint de clave externa
        migrations.RunSQL(
            "ALTER TABLE property_propertyphoto ADD CONSTRAINT property_propertyphoto_property_id_fk FOREIGN KEY (property_id) REFERENCES property_property (id);",
            reverse_sql="ALTER TABLE property_propertyphoto DROP FOREIGN KEY property_propertyphoto_property_id_fk;"
        ),
    ]
