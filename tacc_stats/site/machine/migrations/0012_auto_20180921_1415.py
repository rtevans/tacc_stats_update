# Generated by Django 2.0.7 on 2018-09-21 19:15

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('machine', '0011_auto_20180801_1554'),
    ]

    operations = [
        migrations.AddField(
            model_name='job',
            name='avg_sf_evictions',
            field=models.BigIntegerField(null=True),
        ),
        migrations.AddField(
            model_name='job',
            name='max_sf_evictions',
            field=models.BigIntegerField(null=True),
        ),
    ]
