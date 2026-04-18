from miio.chuangmi_camera import Camera

# Potrzebne dane:
# - IP kamery w sieci lokalnej lub hostname
# - Device token (można znaleźć w aplikacji Xiaomi)

camera = Camera("192.168.1.24", token="VuaO+zElR6Dv2tInJ78RrKG7ye43OltHH3IET6LiVW4DSqXnoWdguQDCsME0TAOvliILsWbiEsPcrU/Ew0PEqoUbaJzMKY0Bb6cdzStWnw/MNcFy965zzv4Szl9JH9LTJqLExxQeIi5TeaPiwHrEpQh4FTdGjcw8tGBte069vd5vD6hja6Pft2U74CLW5Vl0IQkLNoP5tVkXrbVi44niSldYrZNuJshOyJJHr1Zkopc=")

# Stream RTSP
stream_url = camera.get_rtsp_url()
print(stream_url)

# Zwraca coś typu: rtsp://192.168.1.100:554/...