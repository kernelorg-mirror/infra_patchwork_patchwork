# SPDX-License-Identifier: GPL-2.0-or-later

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('patchwork', '0053_series_ordering_indexes'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='event',
            index=models.Index(fields=['date'], name='event_date_idx'),
        ),
        migrations.AddIndex(
            model_name='event',
            index=models.Index(
                fields=['project', 'date'], name='event_project_date_idx'
            ),
        ),
    ]
