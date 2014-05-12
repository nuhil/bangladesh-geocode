-- phpMyAdmin SQL Dump
-- version 3.5.7
-- http://www.phpmyadmin.net
--
-- Host: localhost
-- Generation Time: May 12, 2014 at 10:08 AM
-- Server version: 5.5.29
-- PHP Version: 5.4.10

SET SQL_MODE="NO_AUTO_VALUE_ON_ZERO";
SET time_zone = "+00:00";

--
-- Database: `bd_geocode`
--

-- --------------------------------------------------------

--
-- Table structure for table `districts`
--

CREATE TABLE `districts` (
  `id` int(2) unsigned NOT NULL AUTO_INCREMENT,
  `division_id` int(2) unsigned NOT NULL,
  `name` varchar(30) NOT NULL,
  `bn_name` varchar(50) NOT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB  DEFAULT CHARSET=utf8 AUTO_INCREMENT=65 ;

--
-- Dumping data for table `districts`
--

INSERT INTO `districts` (`id`, `division_id`, `name`, `bn_name`) VALUES
(1, 3, 'Dhaka', 'ঢাকা'),
(2, 3, 'Faridpur', 'ফরিদপুর'),
(3, 3, 'Gazipur', 'গাজীপুর'),
(4, 3, 'Gopalganj', 'গোপালগঞ্জ'),
(5, 3, 'Jamalpur', 'জামালপুর'),
(6, 3, 'Kishoreganj', 'কিশোরগঞ্জ'),
(7, 3, 'Madaripur', 'মাদারীপুর'),
(8, 3, 'Manikganj', 'মানিকগঞ্জ'),
(9, 3, 'Munshiganj', 'মুন্সিগঞ্জ'),
(10, 3, 'Mymensingh', 'ময়মনসিং'),
(11, 3, 'Narayanganj', 'নারায়াণগঞ্জ'),
(12, 3, 'Narsingdi', 'নরসিংদী'),
(13, 3, 'Netrokona', 'নেত্রকোনা'),
(14, 3, 'Rajbari', 'রাজবাড়ি'),
(15, 3, 'Shariatpur', 'শরীয়তপুর'),
(16, 3, 'Sherpur', 'শেরপুর'),
(17, 3, 'Tangail', 'টাঙ্গাইল'),
(18, 5, 'Bogra', 'বগুড়া'),
(19, 5, 'Joypurhat', 'জয়পুরহাট'),
(20, 5, 'Naogaon', 'নওগাঁ'),
(21, 5, 'Natore', 'নাটোর'),
(22, 5, 'Nawabganj', 'নবাবগঞ্জ'),
(23, 5, 'Pabna', 'পাবনা'),
(24, 5, 'Rajshahi', 'রাজশাহী'),
(25, 5, 'Sirajgonj', 'সিরাজগঞ্জ'),
(26, 6, 'Dinajpur', 'দিনাজপুর'),
(27, 6, 'Gaibandha', 'গাইবান্ধা'),
(28, 6, 'Kurigram', 'কুড়িগ্রাম'),
(29, 6, 'Lalmonirhat', 'লালমনিরহাট'),
(30, 6, 'Nilphamari', 'নীলফামারী'),
(31, 6, 'Panchagarh', 'পঞ্চগড়'),
(32, 6, 'Rangpur', 'রংপুর'),
(33, 6, 'Thakurgaon', 'ঠাকুরগাঁও'),
(34, 1, 'Barguna', 'বরগুনা'),
(35, 1, 'Barisal', 'বরিশাল'),
(36, 1, 'Bhola', 'ভোলা'),
(37, 1, 'Jhalokati', 'ঝালকাঠি'),
(38, 1, 'Patuakhali', 'পটুয়াখালী'),
(39, 1, 'Pirojpur', 'পিরোজপুর'),
(40, 2, 'Bandarban', 'বান্দরবান'),
(41, 2, 'Brahmanbaria', 'ব্রাহ্মণবাড়িয়া'),
(42, 2, 'Chandpur', 'চাঁদপুর'),
(43, 2, 'Chittagong', 'চট্টগ্রাম'),
(44, 2, 'Comilla', 'কুমিল্লা'),
(45, 2, 'Cox''s Bazar', 'কক্স বাজার'),
(46, 2, 'Feni', 'ফেনী'),
(47, 2, 'Khagrachari', 'খাগড়াছড়ি'),
(48, 2, 'Lakshmipur', 'লক্ষ্মীপুর'),
(49, 2, 'Noakhali', 'নোয়াখালী'),
(50, 2, 'Rangamati', 'রাঙ্গামাটি'),
(51, 7, 'Habiganj', 'হবিগঞ্জ'),
(52, 7, 'Maulvibazar', 'মৌলভীবাজার'),
(53, 7, 'Sunamganj', 'সুনামগঞ্জ'),
(54, 7, 'Sylhet', 'সিলেট'),
(55, 4, 'Bagerhat', 'বাগেরহাট'),
(56, 4, 'Chuadanga', 'চুয়াডাঙ্গা'),
(57, 4, 'Jessore', 'যশোর'),
(58, 4, 'Jhenaidah', 'ঝিনাইদহ'),
(59, 4, 'Khulna', 'খুলনা'),
(60, 4, 'Kushtia', 'কুষ্টিয়া'),
(61, 4, 'Magura', 'মাগুরা'),
(62, 4, 'Meherpur', 'মেহেরপুর'),
(63, 4, 'Narail', 'নড়াইল'),
(64, 4, 'Satkhira', 'সাতক্ষীরা');