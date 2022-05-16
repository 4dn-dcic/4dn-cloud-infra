echo "Linking app.py to correct app - ensure your branch has locked the correct foursight!"
if test -f app.py; then
  echo "app.py already linked! Assuming you want to link back to cgap."
  ls -lah | grep app.py
  rm app.py
  ln -s app-cgap.py app.py
  ls -lah | grep app.py
else
  echo "app.py not set - linking to fourfront"
  ln -s app-fourfront.py app.py
  ls -lah | grep app.py
fi
