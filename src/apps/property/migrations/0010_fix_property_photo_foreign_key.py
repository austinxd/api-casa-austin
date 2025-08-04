
from django.db import migrations, models
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ('property', '0009_add_property_photos'),
    ]

    operations = [
        # First, drop the foreign key constraint
        migrations.RunSQL(
            "ALTER TABLE property_propertyphoto DROP FOREIGN KEY property_propertypho_property_id_c1b22252_fk_property_;",
            reverse_sql="-- No reverse SQL needed"
        ),
        
        # Change the property_id column to match the Property.id type (UUID)
        migrations.RunSQL(
            "ALTER TABLE property_propertyphoto MODIFY COLUMN property_id CHAR(32) NOT NULL;",
            reverse_sql="ALTER TABLE property_propertyphoto MODIFY COLUMN property_id INT NOT NULL;"
        ),
        
        # Re-add the foreign key constraint
        migrations.RunSQL(
            "ALTER TABLE property_propertyphoto ADD CONSTRAINT property_propertypho_property_id_c1b22252_fk_property_ FOREIGN KEY (property_id) REFERENCES property_property (id);",
            reverse_sql="ALTER TABLE property_propertyphoto DROP FOREIGN KEY property_propertypho_property_id_c1b22252_fk_property_;"
        ),
    ]
