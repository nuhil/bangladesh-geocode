Bangladesh geoCode
==================

Division, District and Upazila level fully mapped MySQL Database. Import all three `sql` files in your DB and make Join Queries to get your desired geo information. 

> All information, content and spelling has been taken from wikipedia.org, maps.google.com

###### Currently has following columns
* division name english
* division name bangla
* district name mapped with division
* district name english
* district name bangla
* district commissioner's (DC) office - latitude (3 meter accuracy)
* district commissioner's (DC )office - longitude (3 meter accuracy)
* district's government verified website address
* upazila name mapped with district
* upazila name english
* upazila name bangla

###### Upcoming columns
* area
* population

###### Division to Unions bangla name only. No GEO Code at this part. 
> All in one Table. Relation using same table ParentID. and Label for show all data by label
> Labels are assign like. 1 = Division, 2 = District, 3 = Upazila & 4 = Union
* Divisions
* Districts
* Upazillas
* Unions [10~20 Bangla name missing due to English name only. I will try to update them latter]
* Data collected for government website for developer. Link: http://bangladesh.gov.bd/site/view/union-list/ 
* Total Record = 5035 :) 

Feel free to find and contact me at [Nuhil.net](http://nuhil.net "Go To My Blog")