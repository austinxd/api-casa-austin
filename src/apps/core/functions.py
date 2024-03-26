import os

def recipt_directory_path(instance, filename):
    upload_to = os.path.join('rental_recipt', str(instance.reservation.id), filename)
    return upload_to